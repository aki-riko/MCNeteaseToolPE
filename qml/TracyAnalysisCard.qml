// SPDX-License-Identifier: GPL-3.0-or-later
// 原生 Tracy 函数热点抓取与前后采样对比卡片。
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
    readonly property var selectedSummary: _captureById(state.selectedCaptureId || "")
    readonly property var diffRows: {
        var rows = []
        var improved = diff.improved || []
        var regressed = diff.regressed || []
        for (var i = 0; i < improved.length; i++) {
            var win = Object.assign({}, improved[i])
            win.kind = "improved"
            rows.push(win)
        }
        for (var j = 0; j < regressed.length; j++) {
            var loss = Object.assign({}, regressed[j])
            loss.kind = "regressed"
            rows.push(loss)
        }
        return rows
    }

    width: parent ? parent.width : 0
    autoHeight: true

    function _captureIndex(captureId) {
        for (var i = 0; i < captures.length; i++) {
            if (String(captures[i].id) === String(captureId)) return i
        }
        return -1
    }

    function _captureById(captureId) {
        var index = _captureIndex(captureId)
        return index >= 0 ? captures[index] : ({})
    }

    function _number(value, decimals) {
        return Number(value || 0).toFixed(decimals)
    }

    Column {
        width: parent ? parent.width : 0
        spacing: Enums.spacing.m

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.m

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Enums.spacing.xxs
                Label {
                    text: qsTr("函数热点与前后对比")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.subtitle
                    font.bold: true
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("直连 ModPC 内嵌 Tracy，归约每个函数的 self / total / calls；采样时请在游戏内触发真实负载。")
                    color: Enums.textColor.secondary
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }
            Tag {
                text: root.state.binAvailable ? qsTr("CLI 已就绪") : qsTr("CLI 缺失")
                status: root.state.binAvailable ? Enums.statusLevel.success : Enums.statusLevel.error
            }
            Tag {
                text: root.state.reachable ? qsTr("ModPC 已连接") : qsTr("ModPC 未连接")
                status: root.state.reachable ? Enums.statusLevel.success : Enums.statusLevel.warning
            }
            Button {
                objectName: "tracyRefreshButton"
                text: qsTr("重新探测")
                style: Enums.button.style_default
                enabled: !root.busy && root.backend !== null
                onClicked: root.backend.refreshTracyStatus()
            }
        }

        Label {
            width: parent ? parent.width : 0
            text: qsTr("端点：%1:%2　CLI：%3")
                  .arg(root.state.address || qsTr("未配置"))
                  .arg(root.state.port || "-")
                  .arg(root.state.binDir || qsTr("未定位"))
            color: Enums.textColor.tertiary
            font.pixelSize: Enums.typography.caption
            wrapMode: Text.WrapAnywhere
        }

        Separator { width: parent ? parent.width : 0 }

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.m

            SpinBox {
                id: durationSpin
                objectName: "tracyDurationSpinBox"
                minimum: 1
                maximum: 60
                stepSize: 1
                decimals: 0
                suffix: qsTr(" 秒")
                value: 10
                enabled: !root.busy
            }
            LineEdit {
                id: filterInput
                objectName: "tracyFilterInput"
                Layout.fillWidth: true
                placeholderText: qsTr("函数名或脚本模块过滤；留空表示全部")
                enabled: !root.busy
            }
            Button {
                objectName: "tracyCaptureBeforeButton"
                text: root.busy ? qsTr("采样中…") : qsTr("采集基线")
                style: Enums.button.style_primary
                enabled: root.ready && !root.busy && root.backend !== null
                onClicked: root.backend.captureTracy(
                    Math.round(durationSpin.value), filterInput.text, "before"
                )
            }
            Button {
                objectName: "tracyCaptureAfterButton"
                text: root.busy ? qsTr("采样中…") : qsTr("采集复测")
                style: Enums.button.style_filled
                enabled: root.ready && !root.busy && root.backend !== null
                onClicked: root.backend.captureTracy(
                    Math.round(durationSpin.value), filterInput.text, "after"
                )
            }
            Button {
                objectName: "tracyClearButton"
                text: qsTr("清空")
                style: Enums.button.style_default
                enabled: !root.busy && root.captures.length > 0
                onClicked: root.backend.clearTracyCaptures()
            }
        }

        Label {
            visible: root.busy
            width: parent ? parent.width : 0
            text: qsTr("正在抓取 Tracy 数据；请保持目标玩法持续运行，窗口结束后会自动生成函数排行。")
            color: Enums.statusLevel.warningColor
            wrapMode: Text.WordWrap
        }

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.m

            Label { text: qsTr("当前采样"); font.bold: true }
            ComboBoxDefault {
                objectName: "tracyCaptureSelector"
                Layout.fillWidth: true
                model: root.captures
                currentIndex: root._captureIndex(root.state.selectedCaptureId || "")
                placeholderText: qsTr("尚无 Tracy 采样")
                enabled: root.captures.length > 0 && !root.busy
                onActivated: function(index) {
                    if (index >= 0 && index < root.captures.length) {
                        root.backend.selectTracyCapture(String(root.captures[index].id))
                    }
                }
            }
            Tag {
                visible: Number(root.selectedSummary.frames || 0) > 0
                text: qsTr("%1 帧 / %2 FPS（窗口平均）")
                      .arg(root.selectedSummary.frames || 0)
                      .arg(root._number(root.selectedSummary.averageFps, 1))
                status: Enums.statusLevel.info
            }
            Tag {
                visible: Number(root.selectedSummary.zones || 0) > 0
                text: qsTr("%1 zones").arg(root.selectedSummary.zones || 0)
                status: Enums.statusLevel.info
            }
        }

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xs
            visible: root.hotspots.length > 0

            RowLayout {
                width: parent ? parent.width : 0
                Label { Layout.fillWidth: true; text: qsTr("函数 / 源文件"); font.bold: true }
                Label { Layout.preferredWidth: 82; text: "self ms"; font.bold: true }
                Label { Layout.preferredWidth: 82; text: "total ms"; font.bold: true }
                Label { Layout.preferredWidth: 68; text: qsTr("调用"); font.bold: true }
                Label { Layout.preferredWidth: 82; text: "ms/帧"; font.bold: true }
                Label { Layout.preferredWidth: 82; text: "ms/次"; font.bold: true }
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
                    Label { Layout.preferredWidth: 82; text: root._number(modelData.selfMs, 3) }
                    Label { Layout.preferredWidth: 82; text: root._number(modelData.totalMs, 3) }
                    Label { Layout.preferredWidth: 68; text: String(modelData.calls || 0) }
                    Label { Layout.preferredWidth: 82; text: root._number(modelData.selfPerFrameMs, 4) }
                    Label { Layout.preferredWidth: 82; text: root._number(modelData.selfPerCallMs, 4) }
                }
            }
        }

        Separator { width: parent ? parent.width : 0; visible: root.captures.length > 0 }

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.m
            visible: root.captures.length > 0

            Label { text: qsTr("基线"); font.bold: true }
            ComboBoxDefault {
                objectName: "tracyBaselineSelector"
                Layout.fillWidth: true
                model: root.captures
                currentIndex: root._captureIndex(root.state.baselineCaptureId || "")
                onActivated: function(index) {
                    if (index >= 0 && index < root.captures.length) {
                        root.backend.selectTracyBaseline(String(root.captures[index].id))
                    }
                }
            }
            Label { text: qsTr("复测"); font.bold: true }
            ComboBoxDefault {
                objectName: "tracyComparisonSelector"
                Layout.fillWidth: true
                model: root.captures
                currentIndex: root._captureIndex(root.state.comparisonCaptureId || "")
                onActivated: function(index) {
                    if (index >= 0 && index < root.captures.length) {
                        root.backend.selectTracyComparison(String(root.captures[index].id))
                    }
                }
            }
            Button {
                objectName: "tracyCompareButton"
                text: qsTr("重新对比")
                style: Enums.button.style_primary
                enabled: !root.busy
                         && String(root.state.baselineCaptureId || "") !== ""
                         && String(root.state.comparisonCaptureId || "") !== ""
                         && String(root.state.baselineCaptureId) !== String(root.state.comparisonCaptureId)
                onClicked: root.backend.compareTracyCaptures(filterInput.text)
            }
        }

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xs
            visible: root.diff.summary !== undefined

            Label {
                width: parent ? parent.width : 0
                text: qsTr("self 总耗时：%1 → %2 ms，变化 %3 ms（%4）")
                      .arg(root._number(root.diff.summary ? root.diff.summary.baseSelfMs : 0, 3))
                      .arg(root._number(root.diff.summary ? root.diff.summary.newSelfMs : 0, 3))
                      .arg(root._number(root.diff.summary ? root.diff.summary.deltaMs : 0, 3))
                      .arg(root.diff.summary && root.diff.summary.percent !== null
                           ? root._number(root.diff.summary.percent, 2) + "%"
                           : qsTr("基线为 0，比例不可计算"))
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
                        text: modelData.kind === "improved" ? qsTr("改善") : qsTr("回退")
                        status: modelData.kind === "improved"
                                ? Enums.statusLevel.success : Enums.statusLevel.warning
                    }
                    Label {
                        Layout.fillWidth: true
                        text: modelData.name
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle
                    }
                    Label {
                        Layout.preferredWidth: 210
                        text: qsTr("%1 → %2 ms　Δ %3 ms")
                              .arg(root._number(modelData.baseMs, 3))
                              .arg(root._number(modelData.newMs, 3))
                              .arg(root._number(modelData.deltaMs, 3))
                    }
                }
            }
        }

        Label {
            width: parent ? parent.width : 0
            text: qsTr("diff 只有在相同设备、场景和采样时长下才可比较；窗口平均 FPS 不等于网易手机集群的 p1/p5 或机审平均帧率。")
            color: Enums.textColor.tertiary
            font.pixelSize: Enums.typography.caption
            wrapMode: Text.WordWrap
        }
    }
}
