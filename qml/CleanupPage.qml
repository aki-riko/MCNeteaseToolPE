// SPDX-License-Identifier: GPL-3.0-or-later
// 垃圾清理页面
// 绑定 per-page 后端 backend:扫描并清理网易 MC 工程中的临时/缓存/构建产物。
// 流程:选择目录 → scan(dir) 列出可清理项 → clean(dir) 执行删除。
import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import PrismQML

Item {
    id: page

    // AsyncQmlPage 注入的 per-page 后端对象 / per-page backend injected by AsyncQmlPage
    property var backend: null
    property string projectDir: ""
    property double totalBytes: 0
    property bool embedded: false

    function urlToPath(url) {
        var s = url.toString()
        s = s.replace(/^file:\/\/\//, "")
        return decodeURIComponent(s)
    }

    function humanSize(bytes) {
        if (bytes < 1024) return bytes + " B"
        var kb = bytes / 1024
        if (kb < 1024) return kb.toFixed(1) + " KB"
        var mb = kb / 1024
        if (mb < 1024) return mb.toFixed(1) + " MB"
        return (mb / 1024).toFixed(2) + " GB"
    }

    onProjectDirChanged: {
        if (!page.embedded) return
        itemModel.clear()
        logModel.clear()
        page.totalBytes = 0
    }

    FolderDialog {
        id: folderDialog
        title: qsTr("选择要清理的工程目录")
        onAccepted: {
            page.projectDir = urlToPath(selectedFolder)
            itemModel.clear()
            logModel.clear()
            backend.scan(page.projectDir)
        }
    }

    ScrollArea {
        id: scroll
        anchors.fill: parent
        padding: page.embedded ? 0 : Enums.spacing.xxxl

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xxl

            // 标题
            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.xs
                visible: !page.embedded
                Row {
                    spacing: Enums.spacing.s
                    Label {
                        text: qsTr("垃圾清理")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.displayLarge
                        font.bold: true
                    }
                    HintIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: 18
                        toolTipText: qsTr("扫描临时文件、缓存与构建产物,清理前会列出待删项与预计释放空间。\n建议清理前对工程做好备份。")
                    }
                }
                Label {
                    text: qsTr("扫描并清理工程中的临时文件、缓存与构建产物,减小打包体积。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }

            // 操作卡片
            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.l

                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("扫描缓存、临时文件和构建产物。确认列表与预计空间后，再执行清理。")
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.bodySmall
                        wrapMode: Text.WordWrap
                        visible: page.embedded
                    }

                    Label {
                        text: qsTr("工程目录")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                        visible: !page.embedded
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m
                        visible: !page.embedded
                        LineEdit {
                            Layout.fillWidth: true
                            text: page.projectDir
                            placeholderText: qsTr("尚未选择工程目录")
                            readOnly: true
                        }
                        Button {
                            text: qsTr("浏览")
                            enabled: !backend.busy
                            onClicked: folderDialog.open()
                        }
                    }

                    Row {
                        spacing: Enums.spacing.m
                        Button {
                            text: qsTr("扫描")
                            enabled: page.projectDir !== "" && !backend.busy
                            onClicked: {
                                itemModel.clear()
                                backend.scan(page.projectDir)
                            }
                        }
                        Button {
                            text: qsTr("清理")
                            style: Enums.button.style_primary
                            enabled: itemModel.count > 0 && !backend.busy
                            onClicked: backend.clean(page.projectDir)
                        }
                    }
                }
            }

            // 可清理项列表
            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: itemModel.count > 0
                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.s
                    Label {
                        text: qsTr("可清理项 (") + itemModel.count + qsTr(" 项,共 ") + page.humanSize(page.totalBytes) + ")"
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Repeater {
                        model: itemModel
                        delegate: Label {
                            width: parent ? parent.width : 0
                            text: model.path
                            color: Enums.textColor.primary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.bodySmall
                            wrapMode: Text.NoWrap
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }

            // 日志
            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: logModel.count > 0
                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.s
                    Label {
                        text: qsTr("日志")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Repeater {
                        model: logModel
                        delegate: Label {
                            width: parent ? parent.width : 0
                            text: model.text
                            color: model.level === "error" ? Enums.statusLevel.errorColor
                                 : model.level === "warning" ? Enums.statusLevel.warningColor
                                 : Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.bodySmall
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: backend
        function onLogMessage(text, level) {
            logModel.append({ "text": text, "level": level })
        }
        function onScanned(items, totalBytes) {
            itemModel.clear()
            page.totalBytes = totalBytes
            for (var i = 0; i < items.length; ++i)
                itemModel.append({ "path": items[i] })
        }
        function onFinished(success, removedCount, freedBytes, message) {
            itemModel.clear()
            logModel.append({ "text": message, "level": success ? "info" : "error" })
        }
    }

    ListModel { id: itemModel }
    ListModel { id: logModel }
}
