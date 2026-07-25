// SPDX-License-Identifier: GPL-3.0-or-later
// UUID 重写页面
// 绑定 per-page 后端 backend:对整个网易 MC 工程重写各 pack 的 UUID。
// 流程:选择工程目录 → analyze(dir) 预览结构 → generate(dir) 执行重写。
import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import PrismQML

Item {
    id: page

    // AsyncQmlPage 注入的 per-page 后端对象 / per-page backend injected by AsyncQmlPage
    property var backend: null
    property string projectDir: ""
    property bool embedded: false

    FolderDialog {
        id: folderDialog
        title: qsTr("选择网易 MC 工程目录")
        onAccepted: {
            page.projectDir = urlToPath(selectedFolder)
            logModel.clear()
            summaryModel.clear()
            backend.analyze(page.projectDir)
        }
    }

    function urlToPath(url) {
        var s = url.toString()
        s = s.replace(/^file:\/\/\//, "")
        return decodeURIComponent(s)
    }

    onProjectDirChanged: {
        if (!page.embedded) return
        summaryModel.clear()
        logModel.clear()
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
                        text: qsTr("UUID 重写")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.displayLarge
                        font.bold: true
                    }
                    HintIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: 18
                        toolTipText: qsTr("重写 manifest.json 中 header 与 modules 的 UUID,并同步依赖引用。\n操作在临时副本上校验后再落盘,不会破坏原始工程。")
                    }
                }
                Label {
                    text: qsTr("对整个网易 MC 工程重写各资源包/行为包的 UUID,避免上架冲突。")
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
                        text: qsTr("重新生成资源包与行为包 UUID，并同步所有依赖引用。先预览结构，再执行写入。")
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
                            onClicked: folderDialog.open()
                        }
                    }

                    Row {
                        spacing: Enums.spacing.m
                        Button {
                            text: qsTr("预览结构")
                            enabled: page.projectDir !== ""
                            onClicked: {
                                summaryModel.clear()
                                backend.analyze(page.projectDir)
                            }
                        }
                        Button {
                            text: qsTr("执行重写")
                            style: Enums.button.style_primary
                            enabled: page.projectDir !== ""
                            onClicked: backend.generate(page.projectDir)
                        }
                    }
                }
            }

            // 结构预览
            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: summaryModel.count > 0
                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.s
                    Label {
                        text: qsTr("工程结构")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Repeater {
                        model: summaryModel
                        delegate: Label {
                            width: parent ? parent.width : 0
                            text: model.line
                            color: Enums.textColor.primary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.body
                            wrapMode: Text.WordWrap
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

    ListModel { id: summaryModel }
    ListModel { id: logModel }

    Connections {
        target: backend
        function onLogMessage(text, level) {
            logModel.append({ "text": text, "level": level })
        }
        function onAnalyzed(structureType, packSummaries) {
            summaryModel.clear()
            summaryModel.append({ "line": qsTr("结构类型:") + structureType })
            for (var i = 0; i < packSummaries.length; ++i)
                summaryModel.append({ "line": packSummaries[i] })
        }
        function onFinished(success, changedManifests, message) {
            logModel.append({ "text": message, "level": success ? "info" : "error" })
        }
    }
}
