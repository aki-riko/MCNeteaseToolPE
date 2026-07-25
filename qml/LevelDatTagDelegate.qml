// SPDX-License-Identifier: GPL-3.0-or-later
// Level.dat 标量编辑行与容器分组行。
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick as QtQ
import QtQuick.Layouts
import PrismQML

Item {
    id: tagRow
    objectName: "levelDatTagRow_" + tagRow.index

    required property string path
    required property string value
    required property string token
    required property bool isNetease
    required property bool editable
    required property bool container
    required property string sourceKind
    required property string editorKind
    required property real minimum
    required property real maximum
    required property int decimals
    required property real stepSize
    required property int index
    property var changes: ({})
    property var scrollTarget: null
    property int totalCount: 0
    readonly property string displayedValue: {
        var changed = tagRow.changes[tagRow.token]
        return changed === undefined ? tagRow.value : String(changed)
    }
    readonly property real rowContentHeight: tagRow.container
                                             ? Enums.controlSize.inputHeight
                                             : scalarRow.implicitHeight

    signal valueEdited(
        string token,
        string originalValue,
        string value,
        bool acceptable
    )

    width: QtQ.ListView.view ? QtQ.ListView.view.width : 0
    height: tagRow.rowContentHeight + Enums.spacing.xs + 1

    Card {
        id: containerRow
        objectName: "levelDatContainerRow_" + tagRow.index
        width: parent ? parent.width : 0
        height: Enums.controlSize.inputHeight
        visible: tagRow.container
        contentPadding: 0
        interactionEnabled: false
        borderRadius: Enums.radius.small
        color: tagRow.isNetease
               ? Enums.statusLevel.getBgColor("info")
               : Enums.stateColor.controlBgHover
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
                color: tagRow.isNetease
                       ? Enums.statusLevel.infoColor
                       : Enums.textColor.secondary
            }
            Label {
                objectName: "levelDatContainerPath_" + tagRow.index
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignVCenter
                text: tagRow.path
                textFormat: Text.PlainText
                color: tagRow.isNetease
                       ? Enums.statusLevel.infoColor
                       : Enums.textColor.primary
                font.family: Enums.fontMonospace
                font.pixelSize: Enums.typography.bodySmall
                font.bold: true
                wrapMode: Text.NoWrap
                elide: Text.ElideMiddle
            }
            Badge {
                objectName: "levelDatContainerSummary_" + tagRow.index
                Layout.alignment: Qt.AlignVCenter
                level: Enums.statusLevel.info
                text: tagRow.value === "" ? qsTr("（空）") : tagRow.value
            }
        }
    }

    RowLayout {
        id: scalarRow
        objectName: "levelDatTagLayout_" + tagRow.index
        width: parent ? parent.width : 0
        visible: !tagRow.container
        spacing: Enums.spacing.m

        Label {
            objectName: "levelDatTagPath_" + tagRow.index
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.alignment: Qt.AlignVCenter
            text: tagRow.path
            textFormat: Text.PlainText
            color: tagRow.isNetease
                   ? Enums.statusLevel.infoColor
                   : Enums.textColor.primary
            font.family: Enums.fontMonospace
            font.pixelSize: Enums.typography.bodySmall
            font.bold: true
            wrapMode: Text.WrapAnywhere
        }
        Label {
            visible: tagRow.isNetease
            Layout.alignment: Qt.AlignVCenter
            text: qsTr("网易")
            textFormat: Text.PlainText
            color: Enums.statusLevel.infoColor
            font.family: Enums.fontFamily
            font.pixelSize: Enums.typography.caption
        }

        LevelDatValueEditor {
            objectName: "levelDatValueEditor_" + tagRow.index
            Layout.preferredWidth: Math.min(420, tagRow.width * 0.38)
            Layout.maximumWidth: Layout.preferredWidth
            Layout.alignment: Qt.AlignVCenter
            visible: tagRow.editable
            editorKind: tagRow.editorKind
            token: tagRow.token
            valueText: tagRow.displayedValue
            minimum: tagRow.minimum
            maximum: tagRow.maximum
            decimals: tagRow.decimals
            stepSize: tagRow.stepSize
            scrollTarget: tagRow.scrollTarget
            onEdited: function(token, value, acceptable) {
                tagRow.valueEdited(token, tagRow.value, value, acceptable)
            }
        }
        TextEdit {
            objectName: "levelDatReadOnlyValue_" + tagRow.index
            Layout.preferredWidth: Math.min(640, tagRow.width * 0.55)
            Layout.maximumWidth: Layout.preferredWidth
            Layout.preferredHeight: Enums.controlSize.inputHeight
            Layout.alignment: Qt.AlignVCenter
            visible: !tagRow.editable
            text: tagRow.displayedValue
            readOnly: true
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
        }
    }

    Separator {
        anchors.bottom: parent.bottom
        width: parent ? parent.width : 0
        visible: tagRow.index < tagRow.totalCount - 1
        lineColor: Enums.dividerColor
    }
}
