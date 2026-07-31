// SPDX-License-Identifier: GPL-3.0-or-later
// 面向日常优化的一键 Tracy 函数热点检测卡片。
import QtQuick
import QtQuick.Layouts
import PrismQML

Card {
    id: root
    objectName: "tracyAnalysisCard"

    property var backend: null
    property var state: ({})
    readonly property var captures: state.captures || []
    readonly property var hotspots: state.hotspots || []
    readonly property var diff: state.diff || ({})
    readonly property bool ready: state.binAvailable === true && state.reachable === true
    readonly property bool busy: state.busy === true
    readonly property bool hasBaseline: String(state.baselineCaptureId || "") !== ""
    readonly property int captureSeconds: Number(state.captureSeconds || 10)
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

    function _number(value, decimals) {
        return Number(value || 0).toFixed(decimals)
    }

    function _buttonText() {
        if (busy) return qsTr("正在检测…")
        if (state.statusChecked !== true) return qsTr("正在准备…")
        if (state.binAvailable !== true) return qsTr("检测组件不可用")
        if (state.reachable !== true) return qsTr("等待 ModPC 启动…")
        return hasBaseline ? qsTr("再次检测并对比") : qsTr("开始检测")
    }

    function _guideText() {
        if (busy) return qsTr("正在检测 %1 秒，请在游戏里正常操作要测的玩法。")
                         .arg(captureSeconds)
        if (state.statusChecked !== true) return qsTr("正在检查检测环境…")
        if (state.binAvailable !== true) return qsTr("检测组件缺失，请重新安装当前版本。")
        if (state.reachable !== true) return qsTr("请先启动 ModPC；检测到游戏后会自动就绪。")
        if (diff.summary !== undefined) return qsTr("对比完成：绿色表示变快，橙色表示变慢。")
        if (hasBaseline) return qsTr("已找到本次热点；修改后再点一次，会自动对比变化。")
        return qsTr("进入要测的场景后点一下，接下来正常操作游戏即可。")
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

    Timer {
        interval: Math.max(250, Number(root.state.probeIntervalMs || 1500))
        repeat: true
        running: root.visible && root.backend !== null && !root.busy
                 && (root.state.statusChecked !== true
                     || (root.state.binAvailable === true
                         && root.state.reachable !== true))
        onTriggered: root.backend.refreshTracyStatus()
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
                    text: qsTr("一键性能检测")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.subtitle
                    font.bold: true
                }
                Label {
                    Layout.fillWidth: true
                    text: root._guideText()
                    color: root.busy ? Enums.statusLevel.warningColor : Enums.textColor.secondary
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }
            Button {
                objectName: "tracyQuickCaptureButton"
                Layout.preferredWidth: 190
                text: root._buttonText()
                style: Enums.button.style_filled
                enabled: root.ready && !root.busy && root.backend !== null
                onClicked: root.backend.captureTracyQuick()
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
