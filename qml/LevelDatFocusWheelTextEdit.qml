// SPDX-License-Identifier: GPL-3.0-or-later
// Level.dat 可聚焦滚轮多行编辑器：失焦滚外层，聚焦滚正文。
pragma ComponentBehavior: Bound

import QtQuick as QtQ
import PrismQML

InputCore {
    id: control

    property alias text: textInput.text
    property bool readOnly: false
    property int wrapMode: QtQ.TextEdit.Wrap
    property int textFormat: QtQ.TextEdit.PlainText
    property bool showScrollIndicator: false
    property var scrollTarget: null
    readonly property real contentY: viewport.contentY
    readonly property real maximumContentY: Math.max(
        0, viewport.contentHeight - viewport.height
    )

    signal textEdited()

    function hasFocus() { return textInput.activeFocus }
    function setFocus() { textInput.forceActiveFocus() }
    function clearFocus() { textInput.focus = false }

    function scrollInner(angleDeltaY) {
        if (control.maximumContentY <= 0 || angleDeltaY === 0) return false
        var delta = -angleDeltaY / 120 * Enums.spacing.xxxl * 3
        var target = Math.max(
            0, Math.min(control.maximumContentY, viewport.contentY + delta)
        )
        if (Math.abs(target - viewport.contentY) < 1) return false
        viewport.contentY = target
        return true
    }

    function scrollOuter(angleDeltaY) {
        if (control.scrollTarget === null
                || typeof control.scrollTarget.scrollWheel !== "function") {
            return false
        }
        control.scrollTarget.scrollWheel(angleDeltaY)
        return true
    }

    function keepCursorVisible() {
        if (!textInput.activeFocus || viewport.height <= 0) return
        var top = textInput.cursorRectangle.y
        var bottom = top + textInput.cursorRectangle.height
        if (top < viewport.contentY) viewport.contentY = Math.max(0, top)
        else if (bottom > viewport.contentY + viewport.height)
            viewport.contentY = Math.min(
                control.maximumContentY, bottom - viewport.height
            )
    }

    focusTarget: textInput
    focused: textInput.activeFocus
    hovered: hoverHandler.hovered
    contentWidth: Enums.controlSize.inputDefaultWidth
    contentHeight: Enums.controlSize.inputDefaultWidth / 2

    QtQ.Flickable {
        id: viewport
        anchors.fill: parent
        anchors.leftMargin: control.paddingLeft
        anchors.rightMargin: control.paddingRight
        anchors.topMargin: control.paddingTop
        anchors.bottomMargin: control.paddingBottom
        contentWidth: textInput.width
        contentHeight: textInput.height
        clip: true
        boundsBehavior: QtQ.Flickable.StopAtBounds
        interactive: contentHeight > height

        onContentHeightChanged: {
            if (contentY > control.maximumContentY)
                contentY = control.maximumContentY
        }

        QtQ.TextEdit {
            id: textInput
            width: viewport.width
            height: contentHeight
            font.family: Enums.fontFamily
            font.pixelSize: control.fontSize
            color: control.inputTextColor
            selectionColor: control.selectionColor
            selectedTextColor: control.selectedTextColor
            selectByMouse: true
            wrapMode: control.wrapMode
            textFormat: control.textFormat
            readOnly: control.readOnly
            enabled: control.enabled
            activeFocusOnPress: true
            cursorVisible: activeFocus

            onTextEdited: control.textEdited()
            onCursorRectangleChanged: control.keepCursorVisible()
        }

        QtQ.WheelHandler {
            blocking: true

            onWheel: function(wheel) {
                var handled = control.hasFocus()
                              && control.scrollInner(wheel.angleDelta.y)
                if (!handled) handled = control.scrollOuter(wheel.angleDelta.y)
                wheel.accepted = handled
            }
        }
    }

    QtQ.Rectangle {
        anchors.right: parent.right
        anchors.rightMargin: Enums.spacing.xxs
        anchors.top: parent.top
        anchors.topMargin: Enums.spacing.l
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Enums.spacing.l
        width: Enums.controlSize.progressBarHeight
        radius: Enums.radius.tiny
        color: control.innerButtonHover
        visible: control.showScrollIndicator
                 && viewport.contentHeight > viewport.height

        QtQ.Rectangle {
            anchors.right: parent.right
            width: parent.width
            radius: parent.radius
            color: Enums.stateColor.dropBorderHover
            height: Math.max(
                Enums.controlSize.textEditScrollThumbMinHeight,
                parent.height * viewport.height / viewport.contentHeight
            )
            y: control.maximumContentY > 0
               ? (parent.height - height)
                 * (viewport.contentY / control.maximumContentY)
               : 0
        }
    }

    QtQ.HoverHandler {
        id: hoverHandler
    }
}
