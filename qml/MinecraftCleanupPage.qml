// SPDX-License-Identifier: GPL-3.0-or-later
// 网易 Minecraft 全局数据目录的安全分类清理页面。
import QtQuick
import QtQuick.Layouts
import PrismQML

Item {
    id: root
    objectName: "minecraftCleanupPage"

    property var backend: null
    property var _state: backend ? (backend.state || {}) : ({})
    readonly property var _texts: _state.texts || ({})
    readonly property bool _busy: backend ? backend.busy === true : false

    function _text(key) {
        return root._texts[key] || ""
    }

    function _refresh() {
        if (backend) backend.refresh()
    }

    function _hasCleanable() {
        var rows = root._state.cleanableRows || []
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].exists === true) return true
        }
        return false
    }

    function _folderMenuItems() {
        return [{ "text": root._text("openFolder"), "icon": "FolderOpen" }]
    }

    function _openFolder(key) {
        if (backend) backend.openFolder(key || "")
    }

    function _confirmClean(key, name, cleanAll, requiresCountdown) {
        cleanDialog.pendingKey = key || ""
        cleanDialog.pendingName = name || ""
        cleanDialog.cleanAll = cleanAll === true
        cleanDialog.requiresCountdown = requiresCountdown === true
        cleanDialog.open()
    }

    Component.onCompleted: _refresh()
    onBackendChanged: _refresh()

    Connections {
        target: root.backend
        ignoreUnknownSignals: true

        function onResult(result) {
            var message = result && result.message ? result.message : ""
            if (message.length > 0) resultToast.show(message, "info")
        }
    }

    Toast {
        id: resultToast
        parent: root
        severity: "info"
        closable: false
        duration: 2500
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
                    text: qsTr("全局缓存清理")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.displayLarge
                    font.bold: true
                }
                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("默认清理网易 Minecraft 日志与缓存；存档、组件、设置等有用数据可单独确认后清理。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }

            Card {
                objectName: "minecraftCleanupSummaryCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.s

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        Icon {
                            icon: "Delete"
                            iconSize: Enums.iconSize.xl
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Enums.spacing.xxs
                            Label {
                                Layout.fillWidth: true
                                text: root._busy && root._state.rootPath === ""
                                      ? root._text("scanning")
                                      : root._state.rootExists === false
                                      ? root._text("missingRoot")
                                      : root._state.reclaimableSize || ""
                                color: Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.titleLarge
                                font.bold: true
                            }
                            Label {
                                Layout.fillWidth: true
                                text: root._text("safeSummary")
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.WordWrap
                            }
                        }
                        Button {
                            objectName: "minecraftCleanupRefreshButton"
                            text: root._text("refresh")
                            style: Enums.button.style_default
                            loading: root._busy
                            enabled: !root._busy
                            onClicked: root._refresh()
                        }
                    }

                    Label {
                        width: parent ? parent.width : 0
                        visible: root._state.rootPath !== ""
                        text: root._state.rootPath || ""
                        color: Enums.textColor.tertiary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle
                    }
                }
            }

            Label {
                text: root._text("recommendedTitle")
                color: Enums.textColor.primary
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.subtitle
                font.bold: true
            }

            Card {
                objectName: "minecraftCleanupCleanableCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Repeater {
                        model: root._state.cleanableRows || []

                        delegate: RowLayout {
                            required property var modelData
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.m

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Enums.spacing.xxs
                                RowLayout {
                                    spacing: Enums.spacing.s
                                    Label {
                                        text: modelData.name || ""
                                        color: Enums.textColor.primary
                                        font.family: Enums.fontFamily
                                        font.pixelSize: Enums.typography.body
                                    }
                                    Badge {
                                        text: root._text("cleanableBadge")
                                        level: Enums.statusLevel.warning
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.description || ""
                                    color: Enums.textColor.secondary
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.caption
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Label {
                                text: (modelData.sizeText || "") + " · " + (modelData.filesText || "")
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                            }
                            Button {
                                objectName: "minecraftCleanupButton_" + modelData.key
                                text: root._text("clean")
                                style: Enums.button.style_filled
                                feature: Enums.button.feature_split
                                menuItems: root._folderMenuItems()
                                enabled: modelData.exists === true && !root._busy
                                onClicked: root._confirmClean(
                                    modelData.key, modelData.name, false, false)
                                onMenuItemClicked: (_index, _text) => root._openFolder(modelData.key)
                            }
                        }
                    }

                    Label {
                        width: parent ? parent.width : 0
                        visible: !root._hasCleanable()
                        text: root._busy ? root._text("scanning") : root._text("empty")
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.body
                    }

                    Separator {
                        width: parent ? parent.width : 0
                        lineColor: Enums.stateColor.border
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        Item { Layout.fillWidth: true }
                        Button {
                            objectName: "minecraftCleanupAllButton"
                            text: root._text("cleanAll")
                            style: Enums.button.style_primary
                            feature: Enums.button.feature_split
                            menuItems: root._folderMenuItems()
                            enabled: root._hasCleanable() && !root._busy
                            onClicked: root._confirmClean("", "", true, false)
                            onMenuItemClicked: (_index, _text) => root._openFolder("")
                        }
                    }
                }
            }

            Label {
                text: root._text("protectedTitle")
                color: Enums.textColor.primary
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.subtitle
                font.bold: true
            }

            Card {
                objectName: "minecraftCleanupProtectedCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Repeater {
                        model: root._state.protectedRows || []

                        delegate: RowLayout {
                            required property var modelData
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.m

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Enums.spacing.xxs
                                RowLayout {
                                    spacing: Enums.spacing.s
                                    Label {
                                        text: modelData.name || ""
                                        color: Enums.textColor.primary
                                        font.family: Enums.fontFamily
                                        font.pixelSize: Enums.typography.body
                                    }
                                    Badge {
                                        text: root._text("protectedBadge")
                                        level: Enums.statusLevel.success
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.description || ""
                                    color: Enums.textColor.secondary
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.caption
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Label {
                                text: (modelData.sizeText || "") + " · " + (modelData.filesText || "")
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                            }
                            Button {
                                objectName: "minecraftCleanupButton_" + modelData.key
                                text: root._text("clean")
                                style: Enums.button.style_filled
                                level: Enums.statusLevel.error
                                feature: Enums.button.feature_split
                                menuItems: root._folderMenuItems()
                                enabled: modelData.exists === true && !root._busy
                                onClicked: root._confirmClean(
                                    modelData.key, modelData.name, false, true)
                                onMenuItemClicked: (_index, _text) => root._openFolder(modelData.key)
                            }
                        }
                    }
                }
            }
        }
    }

    ConfirmDialog {
        id: cleanDialog
        parent: root
        objectName: "minecraftCleanupConfirmDialog"
        property string pendingKey: ""
        property string pendingName: ""
        property bool cleanAll: false
        property bool requiresCountdown: false
        level: requiresCountdown ? Enums.statusLevel.error : Enums.statusLevel.warning
        title: root._text("confirmTitle")
        message: cleanAll
                 ? root._text("confirmAll")
                 : requiresCountdown
                 ? root._text("confirmProtected").replace("{name}", pendingName)
                 : pendingName + "：" + root._text("confirmSingle")
        messageAlignment: Text.AlignLeft
        confirmText: root._text("confirm")
        cancelText: root._text("cancel")
        countdown: requiresCountdown
                   ? Number(root._state.protectedCountdownSeconds || 0)
                   : 0

        onConfirmed: {
            if (!root.backend) return
            if (cleanAll) root.backend.cleanAll()
            else root.backend.clean(pendingKey)
        }
    }
}
