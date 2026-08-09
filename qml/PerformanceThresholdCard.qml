// SPDX-License-Identifier: GPL-3.0-or-later
// 网易公开性能标准的开发阶段参照卡片。
import QtQuick
import PrismQML

Card {
    objectName: "performanceThresholdCard"
    width: parent ? parent.width : 0
    autoHeight: true

    Column {
        width: parent ? parent.width : 0
        spacing: Enums.spacing.m
        Label {
            text: qsTr("网易公开性能标准")
            font.pixelSize: Enums.typography.subtitle
            font.bold: true
        }
        Repeater {
            model: [
                { "name": qsTr("加载时长"), "excellent": "< 10s", "recommended": "< 60s", "pass": "< 120s" },
                { "name": qsTr("内存峰值"), "excellent": "< 150MB", "recommended": "< 300MB", "pass": "< 450MB" },
                { "name": qsTr("平均帧率"), "excellent": "> 55", "recommended": "> 50", "pass": "> 40" }
            ]
            delegate: Column {
                required property var modelData
                width: parent ? parent.width : 0
                spacing: Enums.spacing.xxs
                Label { text: modelData.name; font.bold: true }
                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("优秀 %1　建议 %2　达标 %3")
                          .arg(modelData.excellent)
                          .arg(modelData.recommended)
                          .arg(modelData.pass)
                    color: Enums.textColor.secondary
                    wrapMode: Text.WordWrap
                }
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
