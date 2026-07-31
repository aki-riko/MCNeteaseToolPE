// SPDX-License-Identifier: GPL-3.0-or-later
// 一键持续 Tracy、AirPerf、CPU 与内存监测页面。
import QtQuick
import QtQuick.Layouts
import PrismQML

Item {
    id: root
    objectName: "performancePage"

    property var backend: null
    property var _state: backend ? (backend.state || {}) : ({})
    readonly property var _processes: _state.processes || []
    readonly property var _tracy: _state.tracy || ({})

    function _selectedProcessIndex() {
        var selectedPid = Number(root._state.selectedPid || 0)
        for (var i = 0; i < root._processes.length; i++) {
            if (Number(root._processes[i].pid) === selectedPid) return i
        }
        return -1
    }

    function _refresh() {
        if (backend) backend.refresh()
    }

    Component.onCompleted: _refresh()
    onBackendChanged: _refresh()

    Connections {
        target: root.backend
        ignoreUnknownSignals: true

        function onResult(result) {
            var message = result && result.message ? result.message : ""
            if (message.length > 0) {
                resultToast.show(message, result.success === true ? "success" : "error")
            }
        }
    }

    Toast {
        id: resultToast
        parent: root
        severity: "info"
        closable: false
        duration: 3000
        position: Enums.notification.posBottom
        z: 99
    }

    ScrollArea {
        anchors.fill: parent
        padding: Enums.spacing.xxxl

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xxl

            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.xs

                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("性能诊断")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.displayLarge
                    font.bold: true
                }
                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("进入 MC 自动开始，退出 MC 自动停止；也可手动控制并生成整段会话报告。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }

            TracyAnalysisCard {
                width: parent ? parent.width : 0
                backend: root.backend
                state: root._tracy
                performanceState: root._state
                processes: root._processes
                selectedPid: Number(root._state.selectedPid || 0)
            }

            Card {
                objectName: "performanceProcessCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.l

                    Label {
                        text: qsTr("实时 CPU 与内存")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        ComboBoxDefault {
                            id: processSelector
                            objectName: "performanceProcessSelector"
                            Layout.fillWidth: true
                            model: root._processes
                            currentIndex: root._selectedProcessIndex()
                            placeholderText: qsTr("未发现 ModPC/Minecraft 进程")
                            enabled: root._processes.length > 0
                                     && root._state.unifiedMonitoring !== true
                            onActivated: function(index) {
                                if (backend && index >= 0 && index < root._processes.length) {
                                    backend.selectProcess(Number(root._processes[index].pid))
                                }
                            }
                        }

                        Button {
                            objectName: "performanceClearButton"
                            text: qsTr("清空曲线")
                            style: Enums.button.style_default
                            enabled: root._state.unifiedMonitoring !== true
                            onClicked: backend.clearHistory()
                        }
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        Card {
                            Layout.fillWidth: true
                            autoHeight: true
                            Column {
                                width: parent ? parent.width : 0
                                spacing: Enums.spacing.xxs
                                Label { text: qsTr("CPU"); color: Enums.textColor.secondary }
                                Label {
                                    objectName: "performanceCpuValue"
                                    text: Number(root._state.cpuPercent || 0).toFixed(1) + "%"
                                    font.pixelSize: Enums.typography.titleLarge
                                    font.bold: true
                                }
                            }
                        }
                        Card {
                            Layout.fillWidth: true
                            autoHeight: true
                            Column {
                                width: parent ? parent.width : 0
                                spacing: Enums.spacing.xxs
                                Label { text: qsTr("当前工作集"); color: Enums.textColor.secondary }
                                Label {
                                    objectName: "performanceMemoryValue"
                                    text: Number(root._state.workingSetMb || 0).toFixed(1) + " MB"
                                    font.pixelSize: Enums.typography.titleLarge
                                    font.bold: true
                                }
                            }
                        }
                        Card {
                            Layout.fillWidth: true
                            autoHeight: true
                            Column {
                                width: parent ? parent.width : 0
                                spacing: Enums.spacing.xxs
                                Label { text: qsTr("进程峰值工作集"); color: Enums.textColor.secondary }
                                Label {
                                    objectName: "performancePeakMemoryValue"
                                    text: Number(root._state.peakWorkingSetMb || 0).toFixed(1) + " MB"
                                    font.pixelSize: Enums.typography.titleLarge
                                    font.bold: true
                                }
                            }
                        }
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        ChartView {
                            objectName: "performanceCpuChart"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 240
                            chartType: Enums.chart.type_line
                            chartData: root._state.cpuHistory || []
                            title: qsTr("CPU 使用率")
                            yAxisSuffix: "%"
                            showLegend: false
                            showValues: false
                            showAverage: true
                            showMinMax: true
                            animated: false
                            emptyText: qsTr("开始监测后显示曲线")
                        }
                        ChartView {
                            objectName: "performanceMemoryChart"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 240
                            chartType: Enums.chart.type_line
                            chartData: root._state.memoryHistory || []
                            title: qsTr("进程工作集")
                            yAxisSuffix: " MB"
                            showLegend: false
                            showValues: false
                            showAverage: true
                            showMinMax: true
                            animated: false
                            emptyText: qsTr("开始监测后显示曲线")
                        }
                    }

                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("由上方持续监测统一控制；这里显示 Win PC 进程 CPU 与工作集，不能直接替代网易手机集群机审结论。")
                        color: Enums.statusLevel.warningColor
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Card {
                objectName: "performanceThresholdCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("网易公开性能标准")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Repeater {
                        model: [
                            { "name": qsTr("加载时长"), "excellent": "< 10s", "recommended": "< 60s", "pass": "< 120s" },
                            { "name": qsTr("内存峰值"), "excellent": "< 150MB", "recommended": "< 300MB", "pass": "< 450MB" },
                            { "name": qsTr("平均帧率"), "excellent": "> 55", "recommended": "> 50", "pass": "> 40" }
                        ]
                        delegate: RowLayout {
                            required property var modelData
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.m
                            Label { Layout.fillWidth: true; text: modelData.name; font.bold: true }
                            Label { Layout.preferredWidth: 130; text: qsTr("优秀：") + modelData.excellent }
                            Label { Layout.preferredWidth: 160; text: qsTr("建议：") + modelData.recommended }
                            Label { Layout.preferredWidth: 130; text: qsTr("达标：") + modelData.pass }
                        }
                    }
                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("官方未公开采样窗口、场景脚本、FPS 数据源和卡顿阈值，因此这些数值仅作开发阶段参照。")
                        color: Enums.textColor.tertiary
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
