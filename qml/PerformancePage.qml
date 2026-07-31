// SPDX-License-Identifier: GPL-3.0-or-later
// 官方性能工具桥接与 ModPC 本地进程监测页面。
import QtQuick
import QtQuick.Layouts
import PrismQML

Item {
    id: root
    objectName: "performancePage"

    property var backend: null
    property var _state: backend ? (backend.state || {}) : ({})
    readonly property var _tools: _state.tools || ({})
    readonly property var _processes: _state.processes || []

    function _tool(key) {
        return root._tools[key] || ({ "available": false, "path": "" })
    }

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
                    text: qsTr("桥接 MCStudio 官方工具，并实时观察 ModPC 进程的 CPU 与工作集变化。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }

            Card {
                objectName: "performanceOfficialToolsCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        Icon { icon: "Toolbox"; iconSize: Enums.iconSize.xl }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Enums.spacing.xxs
                            Label {
                                text: qsTr("MCStudio 官方工具")
                                color: Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.subtitle
                                font.bold: true
                            }
                            Label {
                                Layout.fillWidth: true
                                text: root._state.mcStudioRoot
                                      ? root._state.mcStudioRoot
                                      : qsTr("未找到 MCStudio；可用 MCNETEASE_MCSTUDIO_ROOT 指定安装目录")
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.NoWrap
                                elide: Text.ElideMiddle
                            }
                        }
                        Button {
                            objectName: "performanceRefreshButton"
                            text: qsTr("重新检测")
                            style: Enums.button.style_default
                            onClicked: root._refresh()
                        }
                    }

                    Separator { width: parent ? parent.width : 0 }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Enums.spacing.xxs
                            RowLayout {
                                spacing: Enums.spacing.s
                                Label { text: qsTr("方块探针"); font.bold: true }
                                Badge {
                                    text: root._tool("tracy").available ? qsTr("已安装") : qsTr("未找到")
                                    level: root._tool("tracy").available
                                           ? Enums.statusLevel.success : Enums.statusLevel.warning
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("启动 Tracy Profiler，连接 ModPC 后逐帧查看主线程与 MC_SERVER 调用区间。")
                                color: Enums.textColor.secondary
                                wrapMode: Text.WordWrap
                            }
                        }
                        Button {
                            objectName: "launchTracyButton"
                            text: qsTr("启动 Tracy")
                            style: Enums.button.style_primary
                            enabled: root._tool("tracy").available === true
                            onClicked: backend.launchTracy()
                        }
                    }

                    Separator { width: parent ? parent.width : 0 }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Enums.spacing.xxs
                            RowLayout {
                                spacing: Enums.spacing.s
                                Label { text: qsTr("方块易测"); font.bold: true }
                                Badge {
                                    text: root._tool("airperf").available ? qsTr("已安装") : qsTr("未找到")
                                    level: root._tool("airperf").available
                                           ? Enums.statusLevel.success : Enums.statusLevel.warning
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("启动 AirPerf，对 Android、iOS 或 Win PC 设备执行场景化性能采集。")
                                color: Enums.textColor.secondary
                                wrapMode: Text.WordWrap
                            }
                        }
                        Button {
                            objectName: "launchAirPerfButton"
                            text: qsTr("启动 AirPerf")
                            style: Enums.button.style_primary
                            enabled: root._tool("airperf").available === true
                            onClicked: backend.launchAirPerf()
                        }
                    }
                }
            }

            Card {
                objectName: "performanceProcessCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.l

                    Label {
                        text: qsTr("ModPC 进程监测")
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
                            enabled: root._processes.length > 0 && root._state.monitoring !== true
                            onActivated: function(index) {
                                if (backend && index >= 0 && index < root._processes.length) {
                                    backend.selectProcess(Number(root._processes[index].pid))
                                }
                            }
                        }

                        Button {
                            objectName: "performanceMonitorButton"
                            text: root._state.monitoring ? qsTr("停止监测") : qsTr("开始监测")
                            style: root._state.monitoring
                                   ? Enums.button.style_default : Enums.button.style_primary
                            enabled: root._state.samplerAvailable === true
                                     && (root._state.monitoring === true || root._state.selectedPid > 0)
                            onClicked: {
                                if (root._state.monitoring) backend.stopMonitoring()
                                else backend.startMonitoring()
                            }
                        }
                        Button {
                            objectName: "performanceClearButton"
                            text: qsTr("清空曲线")
                            style: Enums.button.style_default
                            enabled: root._state.monitoring !== true
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
                        text: qsTr("这里显示 Win PC 进程 CPU 与工作集，不能直接替代网易手机集群的组件内存、平均帧率或机审结论。")
                        color: Enums.statusLevel.warningColor
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Card {
                objectName: "performanceProfileCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("脚本火焰图")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("复制网易公开的服务端 ModAPI 示例到调试脚本中，调用 StartCpuProfile(秒数) 或 StartMemoryProfile(秒数)，结束后会在 ModPC 目录生成 SVG。提审前必须移除诊断调用。")
                        color: Enums.textColor.secondary
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m
                        Button {
                            objectName: "copyCpuProfileButton"
                            text: qsTr("复制 CPU 分析脚本")
                            style: Enums.button.style_filled
                            onClicked: backend.copyProfileSnippet("cpu")
                        }
                        Button {
                            objectName: "copyMemoryProfileButton"
                            text: qsTr("复制内存分析脚本")
                            style: Enums.button.style_filled
                            onClicked: backend.copyProfileSnippet("memory")
                        }
                        Item { Layout.fillWidth: true }
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
