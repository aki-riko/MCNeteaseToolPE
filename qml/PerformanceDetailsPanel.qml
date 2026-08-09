// SPDX-License-Identifier: GPL-3.0-or-later
// 性能诊断侧边详情：热点、指标、曲线与公开标准的独立承载面板。
import QtQuick
import QtQuick.Layouts
import PrismQML

Item {
    id: root
    objectName: "performanceDetailsPanel"

    property var state: ({})
    property var performanceState: ({})
    property var processes: []
    property int selectedPid: 0
    readonly property var detectedProcess: _processByPid(selectedPid)

    signal closeRequested()

    function _processByPid(pid) {
        for (var i = 0; i < processes.length; i++) {
            if (Number(processes[i].pid) === Number(pid)) return processes[i]
        }
        return processes.length > 0 ? processes[0] : ({})
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Enums.spacing.m

        RowLayout {
            Layout.fillWidth: true
            spacing: Enums.spacing.m

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Enums.spacing.xxs
                Label {
                    text: qsTr("性能详情")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.titleLarge
                    font.bold: true
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("函数明细、会话指标、实时曲线与公开标准")
                    color: Enums.textColor.secondary
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }
            Button {
                objectName: "performanceDetailsCloseButton"
                text: qsTr("关闭")
                onClicked: root.closeRequested()
            }
        }

        Separator { Layout.fillWidth: true }

        ScrollArea {
            id: detailsScrollArea
            objectName: "performanceDetailsScrollArea"
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Vertical
            padding: Enums.spacing.s

            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.l

                PerformanceHotspotDetailsCard {
                    state: root.state
                }

                PerformanceReportDetailsCard {
                    report: root.state.report || ({})
                    detectedProcess: root.detectedProcess
                }

                PerformanceChartsCard {
                    performanceState: root.performanceState
                }

                PerformanceThresholdCard {}

                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("结果用于本机优化，不等于网易手机集群机审成绩。")
                    color: Enums.textColor.tertiary
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
