// SPDX-License-Identifier: GPL-3.0-or-later
// 一键持续 Tracy 与 AirPerf 协议兼容性能监测页面。
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
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
        if (backend) backend.refreshAsync()
    }

    function _prepareDetailsDrawer() {
        var host = root.Window.window
        detailsDrawer.mode = Enums.drawer.mode_inside
        detailsDrawer.position = Enums.position.right
        if (!host || typeof WindowHelper === "undefined" || !WindowHelper) return

        var area = WindowHelper.availableScreenGeometryAt(
            Math.round(host.x + host.width / 2),
            Math.round(host.y + host.height / 2))
        if (!area || Number(area.width || 0) <= 0) return
        var requiredWidth = detailsDrawer.drawerWidth
        var rightSpace = Number(area.x || 0) + Number(area.width || 0)
                         - (host.x + host.width)
        var leftSpace = host.x - Number(area.x || 0)
        if (rightSpace >= requiredWidth) {
            detailsDrawer.mode = Enums.drawer.mode_outside
            detailsDrawer.position = Enums.position.right
        } else if (leftSpace >= requiredWidth) {
            detailsDrawer.mode = Enums.drawer.mode_outside
            detailsDrawer.position = Enums.position.left
        }
    }

    function _openDetailsDrawer() {
        _prepareDetailsDrawer()
        detailsDrawer.open()
    }

    Component.onCompleted: _refresh()
    onBackendChanged: _refresh()
    onVisibleChanged: {
        if (!visible && detailsDrawer.opened) detailsDrawer.close()
    }

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
        id: mainScrollArea
        objectName: "performanceMainScrollArea"
        anchors.fill: parent
        padding: Enums.spacing.xxxl
        orientation: Qt.Vertical

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xxl

            RowLayout {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.l

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Enums.spacing.xs
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("性能诊断")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.displayLarge
                        font.bold: true
                    }
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("进入 MC 自动开始，退出 MC 自动停止；也可手动控制并生成整段会话报告。")
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }
                }
                Button {
                    objectName: "performanceDetailsButton"
                    text: qsTr("性能详情")
                    style: Enums.button.style_filled
                    level: Enums.statusLevel.info
                    onClicked: root._openDetailsDrawer()
                }
            }

            TracyAnalysisCard {
                width: parent ? parent.width : 0
                backend: root.backend
                state: root._tracy
                performanceState: root._state
                processes: root._processes
                selectedPid: Number(root._state.selectedPid || 0)
                onDetailsRequested: root._openDetailsDrawer()
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

                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("由上方持续监测统一控制；完整曲线已移至性能详情，这里保留当前值用于快速判断。")
                        color: Enums.statusLevel.warningColor
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    Drawer {
        id: detailsDrawer
        objectName: "performanceDetailsDrawer"
        anchors.fill: parent
        mode: Enums.drawer.mode_inside
        position: Enums.position.right
        drawerWidth: {
            var hostWidth = root.Window.window ? root.Window.window.width : root.width
            var preferred = Math.max(480, hostWidth * 0.44)
            var insideLimit = Math.max(320, hostWidth - Enums.spacing.xxl)
            return Math.round(Math.min(720, preferred, insideLimit))
        }
        drawerHeight: root.Window.window ? root.Window.window.height : root.height
        modal: mode === Enums.drawer.mode_inside
        animationDuration: Enums.duration.normal

        PerformanceDetailsPanel {
            anchors.fill: parent
            state: root._tracy
            performanceState: root._state
            processes: root._processes
            selectedPid: Number(root._state.selectedPid || 0)
            onCloseRequested: detailsDrawer.close()
        }
    }
}
