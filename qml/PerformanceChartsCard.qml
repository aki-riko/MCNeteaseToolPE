// SPDX-License-Identifier: GPL-3.0-or-later
// 性能诊断抽屉中的实时 CPU 与内存曲线。
import QtQuick
import PrismQML

Card {
    id: root
    objectName: "performanceChartsCard"

    property var performanceState: ({})

    width: parent ? parent.width : 0
    autoHeight: true

    Column {
        width: parent ? parent.width : 0
        spacing: Enums.spacing.m
        Label {
            text: qsTr("实时 CPU 与内存曲线")
            font.pixelSize: Enums.typography.subtitle
            font.bold: true
        }
        ChartView {
            objectName: "performanceCpuChart"
            width: parent ? parent.width : 0
            height: 220
            chartType: Enums.chart.type_line
            chartData: root.performanceState.cpuHistory || []
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
            width: parent ? parent.width : 0
            height: 220
            chartType: Enums.chart.type_line
            chartData: root.performanceState.memoryHistory || []
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
}
