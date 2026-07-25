// SPDX-License-Identifier: GPL-3.0-or-later
// level.dat 标量值编辑器；校验由 PrismQML 输入控件直接承担。
pragma ComponentBehavior: Bound

import QtQuick
import PrismQML

Item {
    id: control
    objectName: "levelDatValueEditor"

    property string editorKind: "none"
    property string token: ""
    property string valueText: ""
    property real minimum: 0
    property real maximum: 0
    property int decimals: 0
    property real stepSize: 1
    property bool editorAcceptable: true
    property var scrollTarget: null
    signal edited(string token, string value, bool acceptable)

    implicitHeight: editorLoader.height
                    + (validationMessage.visible
                       ? editorColumn.spacing + validationMessage.implicitHeight
                       : 0)

    function longIsInRange(text) {
        if (!/^[+-]?[0-9]+$/.test(text)) return false
        var negative = text.charAt(0) === "-"
        var offset = (negative || text.charAt(0) === "+") ? 1 : 0
        var digits = text.substring(offset).replace(/^0+/, "")
        if (digits === "") digits = "0"
        var limit = negative ? "9223372036854775808" : "9223372036854775807"
        if (digits.length !== limit.length) return digits.length < limit.length
        return digits <= limit
    }

    function utf8ByteLength(text) {
        var length = 0
        for (var index = 0; index < text.length; ++index) {
            var code = text.charCodeAt(index)
            if (code <= 0x7f) {
                length += 1
            } else if (code <= 0x7ff) {
                length += 2
            } else if (code >= 0xd800 && code <= 0xdbff) {
                if (index + 1 >= text.length) return -1
                var low = text.charCodeAt(index + 1)
                if (low < 0xdc00 || low > 0xdfff) return -1
                length += 4
                ++index
            } else if (code >= 0xdc00 && code <= 0xdfff) {
                return -1
            } else {
                length += 3
            }
        }
        return length
    }

    Column {
        id: editorColumn
        width: parent ? parent.width : 0
        height: control.implicitHeight
        spacing: Enums.spacing.xs

        Loader {
            id: editorLoader
            width: parent ? parent.width : 0
            height: item ? item.implicitHeight : 0
            sourceComponent: {
                if (control.editorKind === "integer") return integerEditor
                if (control.editorKind === "decimal") return decimalEditor
                if (control.editorKind === "long") return longEditor
                if (control.editorKind === "text") return textEditor
                return null
            }
        }

        Label {
            id: validationMessage
            width: parent ? parent.width : 0
            visible: !control.editorAcceptable
            text: control.editorKind === "long"
                  ? qsTr("请输入 64 位有符号整数")
                  : qsTr("字符串必须是有效文本，且 UTF-8 数据不超过 65535 字节")
            textFormat: Text.PlainText
            color: Enums.statusLevel.errorColor
            font.family: Enums.fontFamily
            font.pixelSize: Enums.typography.caption
            wrapMode: Text.WordWrap
        }
    }

    Component {
        id: integerEditor

        SpinBox {
            property bool acceptableValue: true
            value: Number(control.valueText)
            minimum: control.minimum
            maximum: control.maximum
            decimals: 0
            stepSize: 1
            onValueModified: function(newValue) {
                control.edited(control.token, String(Math.round(newValue)), true)
            }
        }
    }

    Component {
        id: decimalEditor

        SpinBox {
            property bool acceptableValue: true
            function formatted(number) {
                return Number(number).toFixed(control.decimals)
            }
            type: Enums.input.spinbox_double
            value: Number(control.valueText)
            minimum: control.minimum
            maximum: control.maximum
            decimals: control.decimals
            stepSize: control.stepSize
            onValueModified: function(newValue) {
                if (formatted(newValue) === formatted(control.valueText)) return
                control.edited(control.token, String(newValue), true)
            }
        }
    }

    Component {
        id: longEditor

        LineEdit {
            property bool acceptableValue: acceptableInput && control.longIsInRange(text)
            text: control.valueText
            maximumLength: 20
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            validator: RegularExpressionValidator {
                regularExpression: /^[+-]?[0-9]+$/
            }
            onAcceptableValueChanged: control.editorAcceptable = acceptableValue
            Component.onCompleted: control.editorAcceptable = acceptableValue
            onTextEdited: function(newText) {
                control.edited(control.token, newText, acceptableValue)
            }
        }
    }

    Component {
        id: textEditor

        LevelDatFocusWheelTextEdit {
            id: multilineEditor
            objectName: "levelDatMultilineTextEditor"
            readonly property int byteLength: control.utf8ByteLength(text)
            property bool acceptableValue: byteLength >= 0 && byteLength <= 65535
            readonly property bool needsMultipleLines: text.indexOf("\n") >= 0
                                                        || text.length > 80
            text: control.valueText
            contentHeight: needsMultipleLines
                           ? Enums.controlSize.inputDefaultWidth / 2
                           : Enums.controlSize.inputHeight
            showScrollIndicator: true
            scrollTarget: control.scrollTarget
            onAcceptableValueChanged: control.editorAcceptable = acceptableValue
            Component.onCompleted: control.editorAcceptable = acceptableValue
            onTextEdited: {
                control.edited(control.token, text, acceptableValue)
            }
        }
    }
}
