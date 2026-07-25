// SPDX-License-Identifier: GPL-3.0-or-later
// Level.dat 数据页共用的虚拟列表、平滑滚轮与滚动条。
pragma ComponentBehavior: Bound

import QtQuick
import PrismQML

Item {
    id: control

    property var model: null
    property Component delegate: null
    property int cacheBuffer: 0
    readonly property real contentY: scrollArea.contentY
    readonly property real contentHeight: scrollArea.contentHeight
    readonly property var listView: scrollArea.flickableItem
    readonly property int count: scrollArea.count
    readonly property bool scrollable: contentHeight > height

    function scrollBy(delta) {
        scrollArea.smoothScrollBy(delta)
    }

    function scrollWheel(angleDeltaY) {
        if (angleDeltaY === 0) return
        scrollArea.smoothScrollBy(
            -angleDeltaY / 120 * scrollArea.scrollStep
        )
    }

    clip: true

    ScrollArea {
        id: scrollArea
        anchors.fill: parent
        type: Enums.scroll.type_list
        model: control.model
        delegate: control.delegate
        reuseItems: true
        listCacheBuffer: control.cacheBuffer
        itemHeight: Enums.controlSize.inputHeight + Enums.spacing.xs + 1
        selectable: false
        showScrollBar: true
        bounceEnabled: false
    }
}
