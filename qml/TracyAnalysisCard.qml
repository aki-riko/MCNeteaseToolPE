// SPDX-License-Identifier: GPL-3.0-or-later
// 面向日常优化的一键 Tracy、AirPerf 与系统指标检测卡片。
import QtQuick
import QtQuick.Layouts
import PrismQML

Card {
    id: root
    objectName: "tracyAnalysisCard"

    property var backend: null
    property var state: ({})
    property var performanceState: ({})
    property var processes: []
    property int selectedPid: 0
    readonly property var captures: state.captures || []
    readonly property var hotspots: state.hotspots || []
    readonly property var diff: state.diff || ({})
    readonly property var report: state.report || ({})
    readonly property var reportMetrics: report.metrics || []
    readonly property var reportHighlights: report.highlights || []
    readonly property var reportRecommendations: report.recommendations || []
    readonly property bool ready: state.binAvailable === true && state.reachable === true
    readonly property bool busy: state.busy === true
    readonly property bool continuousActive: performanceState.unifiedMonitoring === true
                                            || state.continuousActive === true
    readonly property bool stopRequested: state.stopRequested === true
    readonly property bool autoMonitoring: performanceState.autoMonitoring !== false
    readonly property var airperfState: performanceState.airperf || ({})
    readonly property int windowsCompleted: Number(state.windowsCompleted || 0)
    readonly property var detectedProcess: _processByPid(selectedPid)
    readonly property var selectedSummary: _captureById(state.selectedCaptureId || "")
    readonly property var diffRows: {
        var rows = []
        var groups = [
            [diff.improved || [], "improved"],
            [diff.regressed || [], "regressed"],
            [diff.added || [], "added"],
            [diff.removed || [], "removed"]
        ]
        for (var i = 0; i < groups.length; i++) {
            for (var j = 0; j < groups[i][0].length; j++) {
                var row = Object.assign({}, groups[i][0][j])
                row.kind = groups[i][1]
                rows.push(row)
            }
        }
        return rows
    }

    width: parent ? parent.width : 0
    autoHeight: true

    function _captureById(captureId) {
        for (var i = 0; i < captures.length; i++) {
            if (String(captures[i].id) === String(captureId)) return captures[i]
        }
        return ({})
    }

    function _processByPid(pid) {
        for (var i = 0; i < processes.length; i++) {
            if (Number(processes[i].pid) === Number(pid)) return processes[i]
        }
        return processes.length > 0 ? processes[0] : ({})
    }

    function _number(value, decimals) {
        return Number(value || 0).toFixed(decimals)
    }

    function _buttonText() {
        if (stopRequested) return qsTr("正在停止并生成报告…")
        if (continuousActive) return qsTr("停止并生成报告")
        if (state.statusChecked !== true) return qsTr("正在准备…")
        if (state.binAvailable !== true) return qsTr("检测组件不可用")
        if (state.reachable !== true) return qsTr("等待 ModPC 启动…")
        return qsTr("开始持续监测")
    }

    function _guideText() {
        if (stopRequested) return qsTr("CPU/内存与 AirPerf 已停止，正在完成当前 Tracy 窗口并汇总报告。")
        if (continuousActive) {
            if (airperfState.status === "failed") {
                return qsTr("Tracy 与 CPU/内存持续监测中；%1").arg(airperfState.message || qsTr("AirPerf 采集不可用"))
            }
            return qsTr("Tracy、AirPerf、CPU/内存持续监测中，已完成 %1 个窗口；退出 MC 会自动停止。")
                .arg(windowsCompleted)
        }
        if (state.statusChecked !== true) return qsTr("正在检查检测环境…")
        if (state.binAvailable !== true) return qsTr("检测组件缺失，请重新安装当前版本。")
        if (state.reachable !== true) {
            if (detectedProcess.text) {
                return qsTr("已自动识别 %1，正在等待检测服务就绪…")
                    .arg(detectedProcess.text)
            }
            return qsTr("正在自动查找 ModPC；启动后会自动识别。")
        }
        if (detectedProcess.text) {
            return autoMonitoring
                ? qsTr("已自动识别 %1；默认进入 MC 自动开始，退出 MC 自动出报告。")
                    .arg(detectedProcess.text)
                : qsTr("已自动识别 %1；点击开始后会持续监测到手动停止。")
                .arg(detectedProcess.text)
        }
        return autoMonitoring
            ? qsTr("自动监测已开启；进入 MC 后会自动开始。")
            : qsTr("已连接 ModPC；点击开始后持续监测到手动停止。")
    }

    function _diffKindText(kind) {
        if (kind === "improved") return qsTr("变快")
        if (kind === "regressed") return qsTr("变慢")
        if (kind === "added") return qsTr("新增")
        return qsTr("消失")
    }

    function _diffKindStatus(kind) {
        if (kind === "improved") return Enums.statusLevel.success
        if (kind === "regressed") return Enums.statusLevel.warning
        return Enums.statusLevel.info
    }

    function _reportToneStatus(tone) {
        if (tone === "success") return Enums.statusLevel.success
        if (tone === "warning") return Enums.statusLevel.warning
        return Enums.statusLevel.info
    }

    function _reportKindText(kind) {
        if (kind === "regressed") return qsTr("变慢")
        if (kind === "improved") return qsTr("变快")
        if (kind === "added") return qsTr("新增")
        if (kind === "removed") return qsTr("消失")
        return qsTr("热点")
    }

    Column {
        width: parent ? parent.width : 0
        spacing: Enums.spacing.m

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.l

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Enums.spacing.xxs
                Label {
                    text: qsTr("持续性能监测")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.subtitle
                    font.bold: true
                }
                Label {
                    objectName: "tracyGuideText"
                    Layout.fillWidth: true
                    text: root._guideText()
                    color: root.busy ? Enums.statusLevel.warningColor : Enums.textColor.secondary
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }
            Button {
                objectName: "performanceAutoMonitoringButton"
                Layout.preferredWidth: 150
                text: root.autoMonitoring ? qsTr("自动监测：开") : qsTr("自动监测：关")
                style: Enums.button.style_filled
                level: root.autoMonitoring
                       ? Enums.statusLevel.success : Enums.statusLevel.info
                enabled: root.backend !== null && !root.stopRequested
                onClicked: root.backend.setAutoMonitoring(!root.autoMonitoring)
            }
            Button {
                objectName: "performanceUnifiedMonitorButton"
                Layout.preferredWidth: 220
                text: root._buttonText()
                style: Enums.button.style_filled
                level: root.continuousActive && !root.stopRequested
                       ? Enums.statusLevel.warning
                       : root.ready && !root.busy
                         ? Enums.statusLevel.success : Enums.statusLevel.info
                enabled: root.backend !== null
                         && (root.continuousActive
                             ? !root.stopRequested
                             : root.ready && !root.busy && root.selectedPid > 0)
                onClicked: {
                    if (root.continuousActive) root.backend.stopUnifiedMonitoring()
                    else root.backend.startUnifiedMonitoring()
                }
            }
        }

        Separator {
            width: parent ? parent.width : 0
            visible: String(root.report.title || "") !== ""
        }

        Column {
            objectName: "tracyReportSection"
            width: parent ? parent.width : 0
            spacing: Enums.spacing.m
            visible: String(root.report.title || "") !== ""

            RowLayout {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.m
                Label {
                    objectName: "tracyReportTitle"
                    Layout.fillWidth: true
                    text: root.report.title || ""
                    font.pixelSize: Enums.typography.subtitle
                    font.bold: true
                }
                Tag {
                    text: root.report.verdict || qsTr("检测完成")
                    status: root._reportToneStatus(root.report.tone || "info")
                }
            }

            Label {
                objectName: "tracyReportConclusion"
                width: parent ? parent.width : 0
                text: root.report.conclusion || ""
                color: Enums.textColor.primary
                font.bold: true
                wrapMode: Text.WordWrap
            }

            Flow {
                width: parent ? parent.width : 0
                height: childrenRect.height
                spacing: Enums.spacing.s
                Tag {
                    visible: Boolean(root.detectedProcess.text)
                    text: qsTr("进程：%1").arg(root.detectedProcess.text || "")
                    status: Enums.statusLevel.info
                }
                Repeater {
                    model: root.reportMetrics
                    delegate: Tag {
                        required property var modelData
                        text: modelData.label + qsTr("：") + modelData.value
                        status: Enums.statusLevel.info
                    }
                }
            }

            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.xs
                visible: root.reportHighlights.length > 0
                Label { text: qsTr("优先关注"); font.bold: true }
                Repeater {
                    model: root.reportHighlights
                    delegate: RowLayout {
                        required property var modelData
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.s
                        Tag {
                            text: root._reportKindText(modelData.kind)
                            status: root._diffKindStatus(modelData.kind)
                        }
                        Label {
                            Layout.fillWidth: true
                            text: modelData.name
                            wrapMode: Text.NoWrap
                            elide: Text.ElideMiddle
                        }
                        Label {
                            Layout.preferredWidth: 330
                            text: modelData.detail
                            color: Enums.textColor.secondary
                            horizontalAlignment: Text.AlignRight
                            wrapMode: Text.NoWrap
                            elide: Text.ElideLeft
                        }
                    }
                }
            }

            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.xxs
                visible: root.reportRecommendations.length > 0
                Label { text: qsTr("下一步建议"); font.bold: true }
                Repeater {
                    model: root.reportRecommendations
                    delegate: Label {
                        required property var modelData
                        width: parent ? parent.width : 0
                        text: qsTr("• %1").arg(modelData)
                        color: Enums.textColor.secondary
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.m
            visible: root.captures.length > 0

            Label {
                Layout.fillWidth: true
                text: root.diff.summary !== undefined ? qsTr("前后变化") : qsTr("最耗时函数")
                font.bold: true
            }
            Tag {
                text: qsTr("%1 个函数").arg(root.selectedSummary.matchedFunctions || 0)
                status: Enums.statusLevel.info
            }
            Tag {
                visible: Number(root.selectedSummary.averageFps || 0) > 0
                text: qsTr("%1 FPS").arg(root._number(root.selectedSummary.averageFps, 1))
                status: Enums.statusLevel.info
            }
        }

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xs
            visible: root.hotspots.length > 0 && root.diff.summary === undefined

            RowLayout {
                width: parent ? parent.width : 0
                Label { Layout.fillWidth: true; text: qsTr("函数 / 源文件"); font.bold: true }
                Label { Layout.preferredWidth: 100; text: qsTr("自身耗时"); font.bold: true }
                Label { Layout.preferredWidth: 100; text: qsTr("总耗时"); font.bold: true }
                Label { Layout.preferredWidth: 72; text: qsTr("调用"); font.bold: true }
            }
            Repeater {
                model: root.hotspots
                delegate: RowLayout {
                    required property var modelData
                    width: parent ? parent.width : 0
                    Label {
                        Layout.fillWidth: true
                        text: modelData.name
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle
                    }
                    Label {
                        Layout.preferredWidth: 100
                        text: qsTr("%1 ms").arg(root._number(modelData.selfMs, 3))
                    }
                    Label {
                        Layout.preferredWidth: 100
                        text: qsTr("%1 ms").arg(root._number(modelData.totalMs, 3))
                    }
                    Label { Layout.preferredWidth: 72; text: String(modelData.calls || 0) }
                }
            }
        }

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xs
            visible: root.diff.summary !== undefined

            Label {
                width: parent ? parent.width : 0
                text: qsTr("总耗时 %1 → %2 ms（变化 %3 ms）")
                      .arg(root._number(root.diff.summary ? root.diff.summary.baseSelfMs : 0, 3))
                      .arg(root._number(root.diff.summary ? root.diff.summary.newSelfMs : 0, 3))
                      .arg(root._number(root.diff.summary ? root.diff.summary.deltaMs : 0, 3))
                color: root.diff.summary && Number(root.diff.summary.deltaMs) <= 0
                       ? Enums.statusLevel.successColor : Enums.statusLevel.warningColor
                font.bold: true
            }
            Repeater {
                model: root.diffRows
                delegate: RowLayout {
                    required property var modelData
                    width: parent ? parent.width : 0
                    Tag {
                        text: root._diffKindText(modelData.kind)
                        status: root._diffKindStatus(modelData.kind)
                    }
                    Label {
                        Layout.fillWidth: true
                        text: modelData.name
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle
                    }
                    Label {
                        Layout.preferredWidth: 210
                        text: qsTr("%1 → %2 ms　变化 %3 ms")
                              .arg(root._number(modelData.baseMs, 3))
                              .arg(root._number(modelData.newMs, 3))
                              .arg(root._number(modelData.deltaMs, 3))
                    }
                }
            }
        }

        Label {
            width: parent ? parent.width : 0
            text: qsTr("结果用于本机优化，不等于网易机审成绩。")
            color: Enums.textColor.tertiary
            font.pixelSize: Enums.typography.caption
            wrapMode: Text.WordWrap
        }
    }
}
