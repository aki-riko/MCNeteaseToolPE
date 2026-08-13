# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""AirPerf Windows 客户端的 DirectX 帧数据归约兼容实现。"""

from __future__ import annotations

from collections.abc import Mapping


class AirPerfGraphicsAccumulator:
    """按官方 AdapterWin 逻辑归约 DirectX 累积帧数据。"""

    FRAME_JANK_NS = 83_000_000.0
    FRAME_BIG_JANK_NS = 125_000_000.0
    NANOSECONDS_PER_SECOND = 1_000_000_000.0

    def __init__(self) -> None:
        self._frames: list[dict[str, float | bool]] = []
        self._buckets: dict[int, dict[str, object]] = {}

    def feed(self, raw_frames: list[dict[str, object]]) -> dict[str, float]:
        samples = self.feed_all(raw_frames)
        return samples[-1] if samples else {}

    def feed_all(self, raw_frames: list[dict[str, object]]) -> list[dict[str, float]]:
        """逐项返回官方适配器产生的全部已完成秒桶。"""

        for raw_frame in raw_frames:
            self._append_frame(raw_frame)
        completed = self._complete_buckets()
        self._frames = self._frames[-5:]
        return [self._bucket_sample(bucket) for bucket in completed]

    @staticmethod
    def _bucket_sample(bucket: Mapping[str, object]) -> dict[str, float]:
        frame_infos = bucket["FrameInfos"]
        assert isinstance(frame_infos, list)
        frame_times = [float(item["frameTime"]) for item in frame_infos]
        jank_times = [
            float(item["frameTime"])
            for item in frame_infos
            if item.get("isJank") or item.get("isBigJank")
        ]
        return {
            "frameAverageFps": float(bucket["FPS"]),
            "frameDrawCalls": float(bucket["DrawCalls"]),
            "frameTriangleCount": float(bucket["Trangles"]),
            "frameJankCount": float(bucket["JankCount"]),
            "frameBigJankCount": float(bucket["BigJankCount"]),
            "frameTimeMaxMs": max(frame_times, default=0.0) / 1_000_000.0,
            "frameStutterCount": float(len(jank_times)),
            "frameStutterDurationSumMs": sum(jank_times) / 1_000_000.0,
        }

    @staticmethod
    def _number(raw: Mapping[str, object], key: str) -> float:
        value = raw.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    def _append_frame(self, raw: Mapping[str, object]) -> None:
        frame: dict[str, float | bool] = {
            "time": self._number(raw, "timestamp"),
            "frameTime": 0.0,
            "isJank": False,
            "isBigJank": False,
            "drawCallSum": self._number(raw, "drawCallCount"),
            "drawCall": 0.0,
            "trangleSum": self._number(raw, "trangleCount"),
            "trangle": 0.0,
        }
        self._frames.append(frame)
        if len(self._frames) > 1:
            previous = self._frames[-2]
            frame["drawCall"] = float(frame["drawCallSum"]) - float(previous["drawCallSum"])
            frame["trangle"] = float(frame["trangleSum"]) - float(previous["trangleSum"])
            frame["frameTime"] = float(frame["time"]) - float(previous["time"])
            self._mark_jank(frame)
        self._add_to_bucket(frame)

    def _mark_jank(self, frame: dict[str, float | bool]) -> None:
        frame_time = float(frame["frameTime"])
        if frame_time <= self.FRAME_JANK_NS or len(self._frames) <= 4:
            return
        frame_average = (
            float(self._frames[-2]["time"]) - float(self._frames[-5]["time"])
        ) / 3.0
        if frame_time <= 2.0 * frame_average:
            return
        key = "isBigJank" if frame_time > self.FRAME_BIG_JANK_NS else "isJank"
        frame[key] = True

    def _add_to_bucket(self, frame: dict[str, float | bool]) -> None:
        rounded_time = int(float(frame["time"]) // self.NANOSECONDS_PER_SECOND)
        bucket = self._buckets.setdefault(rounded_time, self._new_bucket(rounded_time))
        frames = bucket["Frames"]
        frame_infos = bucket["FrameInfos"]
        assert isinstance(frames, list) and isinstance(frame_infos, list)
        frames.append(frame)
        frame_infos.append(self._frame_info(frame))
        if frame["isJank"]:
            bucket["JankCount"] = int(bucket["JankCount"]) + 1
        if frame["isBigJank"]:
            bucket["BigJankCount"] = int(bucket["BigJankCount"]) + 1

    @staticmethod
    def _new_bucket(rounded_time: int) -> dict[str, object]:
        return {
            "timestamp": rounded_time,
            "Frames": [],
            "FrameInfos": [],
            "FPS": 0.0,
            "JankCount": 0,
            "BigJankCount": 0,
            "DrawCalls": 0.0,
            "Trangles": 0.0,
        }

    @staticmethod
    def _frame_info(frame: Mapping[str, float | bool]) -> dict[str, float | bool]:
        return {
            "time": frame["time"],
            "frameTime": frame["frameTime"],
            "drawCall": frame["drawCall"],
            "trangle": frame["trangle"],
            "isJank": frame["isJank"],
            "isBigJank": frame["isBigJank"],
        }

    def _complete_buckets(self) -> list[dict[str, object]]:
        completed: list[dict[str, object]] = []
        for rounded_time in sorted(self._buckets)[:-1]:
            bucket = self._buckets.pop(rounded_time)
            self._finalize_bucket(bucket)
            bucket.pop("Frames", None)
            completed.append(bucket)
        return completed

    def _finalize_bucket(self, bucket: dict[str, object]) -> None:
        totals = self._bucket_totals(bucket)
        if totals is None:
            return
        count, duration, draw_calls, triangles = totals
        if duration <= 0 or count <= 0:
            return
        bucket["FPS"] = self.NANOSECONDS_PER_SECOND / (duration / count)
        bucket["DrawCalls"] = draw_calls / count
        bucket["Trangles"] = triangles / count

    @staticmethod
    def _bucket_totals(
        bucket: Mapping[str, object],
    ) -> tuple[int, float, float, float] | None:
        frames = bucket["Frames"]
        infos = bucket["FrameInfos"]
        assert isinstance(frames, list) and isinstance(infos, list)
        if not frames or not infos:
            return None
        first, last = frames[0], frames[-1]
        first_info = infos[0]
        assert isinstance(first, Mapping) and isinstance(last, Mapping)
        assert isinstance(first_info, Mapping)
        if float(first_info["frameTime"]) > 0:
            return AirPerfGraphicsAccumulator._totals_with_carry(
                len(frames), first, last, first_info
            )
        if len(frames) > 1:
            return AirPerfGraphicsAccumulator._totals_between_frames(
                len(frames) - 1, first, last
            )
        return None

    @staticmethod
    def _totals_with_carry(
        count: int,
        first: Mapping[str, object],
        last: Mapping[str, object],
        first_info: Mapping[str, object],
    ) -> tuple[int, float, float, float]:
        return (
            count,
            float(last["time"]) - float(first["time"]) + float(first_info["frameTime"]),
            float(last["drawCallSum"])
            - float(first["drawCallSum"])
            + float(first_info["drawCall"]),
            float(last["trangleSum"])
            - float(first["trangleSum"])
            + float(first_info["trangle"]),
        )

    @staticmethod
    def _totals_between_frames(
        count: int,
        first: Mapping[str, object],
        last: Mapping[str, object],
    ) -> tuple[int, float, float, float]:
        return (
            count,
            float(last["time"]) - float(first["time"]),
            float(last["drawCallSum"]) - float(first["drawCallSum"]),
            float(last["trangleSum"]) - float(first["trangleSum"]),
        )


__all__ = ["AirPerfGraphicsAccumulator"]
