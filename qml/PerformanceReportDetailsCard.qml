// SPDX-License-Identifier: GPL-3.0-or-later
// 性能会话的完整指标与建议，使用稳定 ListModel 避免高频状态刷新重建布局。
import QtQuick
import QtQuick.Layouts
import PrismQML

Card {
    id: root
    objectName: "performanceReportDetailsCard"

    property var report: ({})
    property var detectedProcess: ({})
    readonly property var reportMetrics: report.metrics || []
    readonly property var reportRecommendations: report.recommendations || []

    width: parent ? parent.width : 0
    autoHeight: true

    function _syncMetrics() {
        while (reportMetricsModel.count > reportMetrics.length) {
            reportMetricsModel.remove(reportMetricsModel.count - 1)
        }
        for (var i = 0; i < reportMetrics.length; i++) {
            var payload = {
                "label": String(reportMetrics[i].label || ""),
                "value": String(reportMetrics[i].value || "")
            }
            if (i < reportMetricsModel.count) reportMetricsModel.set(i, payload)
            else reportMetricsModel.append(payload)
        }
    }

    function _syncRecommendations() {
        while (recommendationsModel.count > reportRecommendations.length) {
            recommendationsModel.remove(recommendationsModel.count - 1)
        }
        for (var i = 0; i < reportRecommendations.length; i++) {
            var payload = { "text": String(reportRecommendations[i] || "") }
            if (i < recommendationsModel.count) recommendationsModel.set(i, payload)
            else recommendationsModel.append(payload)
        }
    }

    onReportMetricsChanged: _syncMetrics()
    onReportRecommendationsChanged: _syncRecommendations()
    Component.onCompleted: {
        _syncMetrics()
        _syncRecommendations()
    }

    ListModel { id: reportMetricsModel }
    ListModel { id: recommendationsModel }

    Column {
        width: parent ? parent.width : 0
        spacing: Enums.spacing.m

        RowLayout {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.s
            Label {
                Layout.fillWidth: true
                text: qsTr("会话指标与建议")
                font.pixelSize: Enums.typography.subtitle
                font.bold: true
            }
            Tag {
                visible: Boolean(root.detectedProcess.text)
                text: root.detectedProcess.text || ""
                status: Enums.statusLevel.info
            }
        }

        Label {
            width: parent ? parent.width : 0
            visible: reportMetricsModel.count === 0
            text: qsTr("完成首个检测窗口后显示完整指标。")
            color: Enums.textColor.secondary
            wrapMode: Text.WordWrap
        }

        ScrollArea {
            id: reportMetricsList
            objectName: "performanceReportMetricsList"
            width: parent ? parent.width : 0
            height: 300
            visible: reportMetricsModel.count > 0
            type: Enums.scroll.type_list
            model: reportMetricsModel
            itemHeight: 30
            reuseItems: true
            selectable: false
            bounceEnabled: false

            delegate: Item {
                required property string label
                required property string value
                width: ListView.view ? ListView.view.width : 0
                height: reportMetricsList.itemHeight

                RowLayout {
                    anchors.fill: parent
                    spacing: Enums.spacing.m
                    Label {
                        Layout.fillWidth: true
                        text: label
                        color: Enums.textColor.secondary
                        wrapMode: Text.NoWrap
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.preferredWidth: Math.min(230, Math.max(140, parent.width * 0.44))
                        text: value
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
            visible: recommendationsModel.count > 0
            Label { text: qsTr("下一步建议"); font.bold: true }
            Repeater {
                model: recommendationsModel
                delegate: Item {
                    required property string text
                    width: parent ? parent.width : 0
                    height: 52
                    Label {
                        anchors.fill: parent
                        text: qsTr("• %1").arg(parent.text)
                        color: Enums.textColor.secondary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }
}
