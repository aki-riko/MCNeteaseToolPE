// SPDX-License-Identifier: GPL-3.0-or-later
// 世界数据库编辑行：路径与操作在顶部，完整 JSON 独占下方编辑区。
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick as QtQ
import QtQuick.Layouts
import PrismQML

Item {
    id: dataRow
    objectName: "levelDatExtraDataRow_" + dataRow.index

    required property string path
    required property string value
    required property string fullValue
    required property string token
    required property bool container
    required property bool valueTruncated
    required property int fullValueLength
    required property int liveValidationLimit
    required property int index
    property var backend: null
    property var changes: ({})
    property var scrollTarget: null
    readonly property string displayedValue: {
        var changed = dataRow.changes[dataRow.token]
        return changed === undefined ? dataRow.fullValue : String(changed)
    }
    readonly property int previewLineCount: Math.max(
        1, dataRow.displayedValue.split("\n").length
    )
    readonly property bool deferredValidation: displayedValue.length
                                               > dataRow.liveValidationLimit
    readonly property bool acceptableValue: deferredValidation
                                            || dataRow.validJson(dataRow.displayedValue)
    readonly property real validationHeight: acceptableValue
                                             ? 0
                                             : Enums.controlSize.inputHeightCompact
    readonly property real jsonViewportHeight: Math.min(
        Enums.controlSize.inputDefaultWidth * 0.75,
        Math.max(
            Enums.controlSize.inputHeight * 2,
            dataRow.previewLineCount * Enums.spacing.xxl + Enums.spacing.m * 2
        )
    )
    readonly property real cardHeight: Enums.controlSize.inputHeight
                                       + Enums.spacing.xs
                                       + dataRow.jsonViewportHeight
                                       + dataRow.validationHeight
                                       + Enums.spacing.m * 2
    readonly property real rowContentHeight: dataRow.container
                                             ? Enums.controlSize.inputHeight
                                             : dataRow.cardHeight

    width: QtQ.ListView.view ? QtQ.ListView.view.width : 0
    height: dataRow.rowContentHeight + Enums.spacing.xs

    signal valueEdited(
        string token,
        string originalValue,
        string value,
        bool acceptable
    )

    function validJson(value) {
        try {
            JSON.parse(value)
            return true
        } catch (error) {
            return false
        }
    }

    Card {
        id: containerRow
        objectName: "levelDatExtraDataContainerRow_" + dataRow.index
        width: parent ? parent.width : 0
        height: Enums.controlSize.inputHeight
        visible: dataRow.container
        contentPadding: 0
        interactionEnabled: false
        borderRadius: Enums.radius.small
        color: Enums.statusLevel.getBgColor("info")
        border.width: Enums.border.thin
        border.color: Enums.stateColor.borderLight

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Enums.spacing.m
            anchors.rightMargin: Enums.spacing.m
            spacing: Enums.spacing.m

            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: Enums.border.thick
                Layout.preferredHeight: Enums.controlSize.inputHeightCompact
                radius: Enums.border.thick / 2
                color: Enums.statusLevel.infoColor
            }
            Label {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignVCenter
                text: dataRow.path
                textFormat: Text.PlainText
                color: Enums.statusLevel.infoColor
                font.family: Enums.fontMonospace
                font.pixelSize: Enums.typography.bodySmall
                font.bold: true
                wrapMode: Text.NoWrap
                elide: Text.ElideMiddle
            }
            Badge {
                Layout.alignment: Qt.AlignVCenter
                level: Enums.statusLevel.info
                text: dataRow.value === "" ? qsTr("（空）") : dataRow.value
            }
        }
    }

    Card {
        id: dataCard
        objectName: "levelDatExtraDataCard_" + dataRow.index
        width: parent ? parent.width : 0
        height: dataRow.cardHeight
        visible: !dataRow.container
        contentPadding: 0
        interactionEnabled: false
        borderRadius: Enums.radius.small
        color: Enums.stateColor.controlBg
        border.width: Enums.border.thin
        border.color: Enums.stateColor.borderLight

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Enums.spacing.m
            spacing: Enums.spacing.xs

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: Enums.controlSize.inputHeight
                spacing: Enums.spacing.m

                Label {
                    objectName: "levelDatExtraDataPath_" + dataRow.index
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.alignment: Qt.AlignVCenter
                    text: dataRow.path
                    textFormat: Text.PlainText
                    color: Enums.statusLevel.infoColor
                    font.family: Enums.fontMonospace
                    font.pixelSize: Enums.typography.bodySmall
                    font.bold: true
                    wrapMode: Text.NoWrap
                    elide: Text.ElideMiddle
                }
                Label {
                    Layout.alignment: Qt.AlignVCenter
                    text: qsTr("DB")
                    textFormat: Text.PlainText
                    color: Enums.statusLevel.infoColor
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                }
                Label {
                    objectName: "levelDatExtraDataPreviewStatus_" + dataRow.index
                    Layout.alignment: Qt.AlignVCenter
                    text: dataRow.valueTruncated
                          ? qsTr("完整值 %1 字符").arg(dataRow.displayedValue.length)
                          : qsTr("%1 字符").arg(dataRow.displayedValue.length)
                    textFormat: Text.PlainText
                    color: dataRow.valueTruncated
                           ? Enums.statusLevel.warningColor
                           : Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                }
                Button {
                    objectName: "levelDatCopyFullValue_" + dataRow.index
                    Layout.alignment: Qt.AlignVCenter
                    enabled: dataRow.backend !== null
                    text: qsTr("复制当前 JSON")
                    onClicked: dataRow.backend.copyExtraDataText(dataRow.displayedValue)
                }
            }

            LevelDatFocusWheelTextEdit {
                id: jsonEditor
                objectName: "levelDatExtraDataEditor_" + dataRow.index
                Layout.fillWidth: true
                Layout.preferredHeight: dataRow.jsonViewportHeight
                Layout.minimumHeight: dataRow.jsonViewportHeight
                Layout.maximumHeight: dataRow.jsonViewportHeight
                text: dataRow.displayedValue
                readOnly: false
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                showScrollIndicator: true
                onTextEdited: {
                    dataRow.valueEdited(
                        dataRow.token,
                        dataRow.fullValue,
                        text,
                        dataRow.validJson(text)
                    )
                }
                scrollTarget: dataRow.scrollTarget
            }

            Label {
                Layout.fillWidth: true
                Layout.preferredHeight: dataRow.validationHeight
                visible: !dataRow.acceptableValue
                text: qsTr("JSON 格式无效，修正后才能保存")
                textFormat: Text.PlainText
                color: Enums.statusLevel.errorColor
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.caption
            }
        }
    }
}
