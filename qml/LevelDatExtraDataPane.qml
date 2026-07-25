// SPDX-License-Identifier: GPL-3.0-or-later
// 世界数据库 scriptData 摘要、编辑列表与保存操作。
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import PrismQML

Item {
    id: pane

    property var backend: null
    property var summary: ({})
    property var changes: ({})
    property int changeCount: 0
    property int invalidCount: 0
    property bool busy: false

    signal valueEdited(
        string token,
        string originalValue,
        string value,
        bool acceptable
    )
    signal clearRequested()
    signal saveRequested()

    Card {
        id: summaryCard
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        autoHeight: true
        visible: pane.summary.filePath !== undefined
                 && pane.summary.filePath !== ""

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.s

            Label {
                text: pane.summary.extraDataStatus || qsTr("未检查世界数据库")
                textFormat: Text.PlainText
                color: pane.summary.extraDataFound
                       ? Enums.statusLevel.successColor
                       : pane.summary.levelDbFound
                         ? Enums.statusLevel.warningColor
                         : Enums.textColor.secondary
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.body
                font.bold: true
            }
            Label {
                width: parent ? parent.width : 0
                visible: pane.summary.levelDbFound === true
                text: qsTr("目录：%1").arg(pane.summary.levelDbPath || "")
                textFormat: Text.PlainText
                color: Enums.textColor.secondary
                font.family: Enums.fontMonospace
                font.pixelSize: Enums.typography.bodySmall
                wrapMode: Text.WrapAnywhere
            }
            Label {
                width: parent ? parent.width : 0
                visible: pane.summary.extraDataFound === true
                text: qsTr("sequence：%1　来源：%2　根键：%3　匹配：%4")
                      .arg(pane.summary.extraDataSequence)
                      .arg(pane.summary.extraDataSourceFile)
                      .arg(pane.summary.extraDataEntryCount)
                      .arg(pane.backend ? pane.backend.extraDataTagModel.count : 0)
                textFormat: Text.PlainText
                color: Enums.textColor.secondary
                font.family: Enums.fontMonospace
                font.pixelSize: Enums.typography.bodySmall
                wrapMode: Text.WordWrap
            }
            Label {
                width: parent ? parent.width : 0
                visible: pane.summary.extraDataFound === true
                text: qsTr("地图：%1　撤离点：%2　拉闸方块：%3　闸门控制台：%4")
                      .arg(pane.summary.matchMapCount)
                      .arg(pane.summary.exitPointCount)
                      .arg(pane.summary.switchBlockCount)
                      .arg(pane.summary.gateConsoleCount)
                textFormat: Text.PlainText
                color: Enums.statusLevel.infoColor
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.body
                font.bold: true
                wrapMode: Text.WordWrap
            }
            Label {
                width: parent ? parent.width : 0
                visible: pane.summary.extraDataTruncated === true
                text: qsTr("ExtraData 条目达到安全行数上限；请先缩小数据后再编辑。")
                textFormat: Text.PlainText
                color: Enums.statusLevel.warningColor
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.bodySmall
            }
            RowLayout {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.m

                Label {
                    Layout.fillWidth: true
                    text: pane.invalidCount > 0
                          ? qsTr("%1 项修改不是有效 JSON").arg(pane.invalidCount)
                          : qsTr("已修改 %1 项；保存前会完整备份 db 目录")
                            .arg(pane.changeCount)
                    textFormat: Text.PlainText
                    color: pane.invalidCount > 0
                           ? Enums.statusLevel.errorColor
                           : Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.bodySmall
                }
                Button {
                    text: qsTr("撤销 DB 修改")
                    enabled: pane.changeCount > 0 && !pane.busy
                    onClicked: pane.clearRequested()
                }
                Button {
                    text: pane.busy
                          ? qsTr("正在保存…")
                          : qsTr("保存 %1 项 DB 修改").arg(pane.changeCount)
                    style: Enums.button.style_filled
                    enabled: pane.changeCount > 0
                             && pane.invalidCount === 0
                             && !pane.busy
                             && pane.summary.extraDataTruncated !== true
                    onClicked: pane.saveRequested()
                }
            }
        }
    }

    LevelDatVirtualList {
        id: dataList
        objectName: "levelDatExtraDataList"
        anchors.top: summaryCard.visible ? summaryCard.bottom : parent.top
        anchors.topMargin: summaryCard.visible ? Enums.spacing.m : 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        model: pane.backend ? pane.backend.extraDataTagModel : null
        delegate: LevelDatExtraDataDelegate {
            backend: pane.backend
            changes: pane.changes
            scrollTarget: dataList
            onValueEdited: function(token, originalValue, value, acceptable) {
                pane.valueEdited(token, originalValue, value, acceptable)
            }
        }
    }
}
