// SPDX-License-Identifier: GPL-3.0-or-later
// Tracy 热点与前后变化明细，固定列表视口防止外层滚动范围在刷新时收缩。
import QtQuick
import QtQuick.Layouts
import PrismQML

Card {
    id: root
    objectName: "performanceHotspotDetailsCard"

    property var state: ({})
    readonly property var captures: state.captures || []
    readonly property var hotspots: state.hotspots || []
    readonly property var diff: state.diff || ({})
    readonly property var selectedSummary: _captureById(state.selectedCaptureId || "")
    readonly property int durationColumnWidth: 96
    readonly property int callsColumnWidth: 60

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

    function _syncHotspots() {
        while (hotspotModel.count > hotspots.length) {
            hotspotModel.remove(hotspotModel.count - 1)
        }
        for (var i = 0; i < hotspots.length; i++) {
            var payload = {
                "name": String(hotspots[i].name || ""),
                "selfMs": Number(hotspots[i].selfMs || 0),
                "totalMs": Number(hotspots[i].totalMs || 0),
                "calls": Number(hotspots[i].calls || 0)
            }
            if (i < hotspotModel.count) hotspotModel.set(i, payload)
            else hotspotModel.append(payload)
        }
    }

    function _syncDiffRows() {
        var items = []
        var groups = [
            [diff.improved || [], "improved"],
            [diff.regressed || [], "regressed"],
            [diff.added || [], "added"],
            [diff.removed || [], "removed"]
        ]
        for (var i = 0; i < groups.length; i++) {
            for (var j = 0; j < groups[i][0].length; j++) {
                items.push({
                    "kind": groups[i][1],
                    "name": String(groups[i][0][j].name || ""),
                    "baseMs": Number(groups[i][0][j].baseMs || 0),
                    "newMs": Number(groups[i][0][j].newMs || 0),
                    "deltaMs": Number(groups[i][0][j].deltaMs || 0)
                })
            }
        }
        while (diffRowsModel.count > items.length) {
            diffRowsModel.remove(diffRowsModel.count - 1)
        }
        for (var index = 0; index < items.length; index++) {
            if (index < diffRowsModel.count) diffRowsModel.set(index, items[index])
            else diffRowsModel.append(items[index])
        }
    }

    onHotspotsChanged: _syncHotspots()
    onDiffChanged: _syncDiffRows()
    Component.onCompleted: {
        _syncHotspots()
        _syncDiffRows()
    }

    ListModel { id: hotspotModel }
    ListModel { id: diffRowsModel }

    Column {
        width: parent ? parent.width : 0
        spacing: Enums.spacing.s

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.s
            Label {
                objectName: "tracyHotspotScopeTitle"
                Layout.fillWidth: true
                text: root.diff.summary !== undefined
                      ? qsTr("前后变化")
                      : root.captures.length > 0
                        ? qsTr("当前选中窗口最耗时函数（%1 秒）")
                            .arg(Number(root.selectedSummary.seconds || 0))
                        : qsTr("当前窗口函数明细")
                font.pixelSize: Enums.typography.subtitle
                font.bold: true
            }
            Tag {
                visible: root.captures.length > 0
                text: qsTr("%1 个函数").arg(root.selectedSummary.matchedFunctions || 0)
                status: Enums.statusLevel.info
            }
            Tag {
                objectName: "tracySelectedFrameRateTag"
                visible: Number(root.selectedSummary.averageFps || 0) > 0
                text: qsTr("%1 FrameMark/s").arg(root._number(root.selectedSummary.averageFps, 1))
                status: Enums.statusLevel.info
            }
        }

        Label {
            width: parent ? parent.width : 0
            visible: root.captures.length === 0
            text: qsTr("完成一个 Tracy 检测窗口后显示函数明细。")
            color: Enums.textColor.secondary
            wrapMode: Text.WordWrap
        }

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xxs
            visible: hotspotModel.count > 0 && root.diff.summary === undefined

            RowLayout {
                width: parent ? parent.width : 0
                Label { Layout.fillWidth: true; text: qsTr("函数 / 源文件"); font.bold: true }
                Label {
                    Layout.preferredWidth: root.durationColumnWidth
                    text: qsTr("自身耗时")
                    font.bold: true
                    horizontalAlignment: Text.AlignRight
                }
                Label {
                    Layout.preferredWidth: root.durationColumnWidth
                    text: qsTr("总耗时")
                    font.bold: true
                    horizontalAlignment: Text.AlignRight
                }
                Label {
                    Layout.preferredWidth: root.callsColumnWidth
                    text: qsTr("调用")
                    font.bold: true
                    horizontalAlignment: Text.AlignRight
                }
            }

            ScrollArea {
                id: hotspotList
                objectName: "performanceHotspotList"
                width: parent ? parent.width : 0
                height: 400
                type: Enums.scroll.type_list
                model: hotspotModel
                itemHeight: 32
                reuseItems: true
                selectable: false
                bounceEnabled: false

                delegate: Item {
                    required property string name
                    required property real selfMs
                    required property real totalMs
                    required property real calls
                    width: ListView.view ? ListView.view.width : 0
                    height: hotspotList.itemHeight

                    RowLayout {
                        anchors.fill: parent
                        spacing: Enums.spacing.s
                        Label {
                            Layout.fillWidth: true
                            text: name
                            wrapMode: Text.NoWrap
                            elide: Text.ElideMiddle
                        }
                        Label {
                            Layout.preferredWidth: root.durationColumnWidth
                            text: qsTr("%1 ms").arg(root._number(selfMs, 3))
                            horizontalAlignment: Text.AlignRight
                            wrapMode: Text.NoWrap
                            elide: Text.ElideLeft
                        }
                        Label {
                            Layout.preferredWidth: root.durationColumnWidth
                            text: qsTr("%1 ms").arg(root._number(totalMs, 3))
                            horizontalAlignment: Text.AlignRight
                            wrapMode: Text.NoWrap
                            elide: Text.ElideLeft
                        }
                        Label {
                            Layout.preferredWidth: root.callsColumnWidth
                            text: String(calls)
                            horizontalAlignment: Text.AlignRight
                            wrapMode: Text.NoWrap
                            elide: Text.ElideLeft
                        }
                    }
                }
            }
        }

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.s
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
                wrapMode: Text.WordWrap
            }

            ScrollArea {
                id: diffList
                objectName: "performanceDiffList"
                width: parent ? parent.width : 0
                height: Math.min(360, Math.max(120, diffRowsModel.count * 36))
                type: Enums.scroll.type_list
                model: diffRowsModel
                itemHeight: 36
                reuseItems: true
                selectable: false
                bounceEnabled: false

                delegate: Item {
                    required property string kind
                    required property string name
                    required property real baseMs
                    required property real newMs
                    required property real deltaMs
                    width: ListView.view ? ListView.view.width : 0
                    height: diffList.itemHeight

                    RowLayout {
                        anchors.fill: parent
                        spacing: Enums.spacing.s
                        Tag {
                            text: root._diffKindText(kind)
                            status: root._diffKindStatus(kind)
                        }
                        Label {
                            Layout.fillWidth: true
                            text: name
                            wrapMode: Text.NoWrap
                            elide: Text.ElideMiddle
                        }
                        Label {
                            Layout.preferredWidth: 190
                            text: qsTr("%1 → %2 ms　%3 ms")
                                  .arg(root._number(baseMs, 3))
                                  .arg(root._number(newMs, 3))
                                  .arg(root._number(deltaMs, 3))
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                }
            }
        }
    }
}
