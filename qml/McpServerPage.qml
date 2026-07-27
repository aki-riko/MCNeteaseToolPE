// SPDX-License-Identifier: GPL-3.0-or-later
// Application-lifetime Model Context Protocol server status page.
// MCP 服务随程序自动启停；工程路径由每次工具调用从提示词传入。
import QtQuick
import QtQuick as QtQ
import QtQuick.Layouts
import PrismQML

Item {
    id: page
    objectName: "mcpServerPage"

    property var backend: null
    readonly property bool active: backend ? backend.active : false
    readonly property bool starting: backend ? backend.starting : false
    readonly property bool running: backend ? backend.running : false
    readonly property string endpoint: backend ? backend.endpoint : ""
    readonly property string accessPrompt: backend ? backend.accessPrompt : ""
    readonly property int endpointCount: page.endpoint === "" ? 0 : 1

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
                    text: qsTr("MCP 服务器")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.displayLarge
                    font.bold: true
                }

                RowLayout {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        Layout.fillWidth: true
                        text: backend ? backend.status : qsTr("MCP 后端不可用")
                        color: page.running ? Enums.statusLevel.successColor
                               : page.starting ? Enums.statusLevel.warningColor
                               : Enums.statusLevel.errorColor
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.NoWrap
                        elide: Text.ElideRight
                    }

                    Tag {
                        text: qsTr("接入 %1 个端点").arg(page.endpointCount)
                        status: page.running ? Enums.statusLevel.success
                                : page.starting ? Enums.statusLevel.warning
                                : Enums.statusLevel.error
                    }

                    Button {
                        objectName: "mcpRetryButton"
                        visible: !page.active
                        text: qsTr("重新启动")
                        style: Enums.button.style_primary
                        enabled: backend !== null
                        onClicked: backend.start()
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("接入 Prompt")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }

                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("复制下面的 Prompt 发给 AI，让它完成 MCP 配置并验证实际连接。")
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }

                    QtQ.TextEdit {
                        objectName: "mcpAccessPromptField"
                        width: parent ? parent.width : 0
                        height: contentHeight
                        text: page.accessPrompt
                        readOnly: true
                        selectByMouse: true
                        wrapMode: QtQ.TextEdit.Wrap
                        textFormat: QtQ.TextEdit.PlainText
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.bodySmall
                    }

                    RowLayout {
                        width: parent ? parent.width : 0

                        Item { Layout.fillWidth: true }

                        Button {
                            objectName: "mcpCopyAccessPromptButton"
                            text: qsTr("复制接入 Prompt")
                            style: Enums.button.style_primary
                            enabled: backend !== null && page.accessPrompt !== ""
                            onClicked: backend.copyAccessPrompt()
                        }
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("可用工具")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }

                    Repeater {
                        model: [
                            { "name": "process_project", "mode": qsTr("写入"),
                              "detail": qsTr("一键执行清理、审核、UUID 和 ZIP。") },
                            { "name": "inspect_world_data", "mode": qsTr("只读"),
                              "detail": qsTr("读取、搜索世界数据，或按 token 返回完整值。") },
                            { "name": "update_level_dat", "mode": qsTr("写入"),
                              "detail": qsTr("备份并保存原版与网易 NBT 修改。") },
                            { "name": "update_world_database", "mode": qsTr("写入"),
                              "detail": qsTr("完整备份 db 后保存 scriptData。") },
                            { "name": "scan_global_minecraft_data", "mode": qsTr("只读"),
                              "detail": qsTr("返回分类、recommended_category 和一次性 scan_token。") },
                            { "name": "clean_global_minecraft_data", "mode": qsTr("写入"),
                              "detail": qsTr("凭一次性 scan_token 清理，保护项需双重确认。") }
                        ]

                        delegate: RowLayout {
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.m

                            Label {
                                Layout.preferredWidth: 190
                                text: modelData.name
                                color: Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                            }
                            Tag {
                                text: modelData.mode
                                status: modelData.mode === qsTr("只读")
                                        ? Enums.statusLevel.success
                                        : Enums.statusLevel.warning
                            }
                            Label {
                                Layout.fillWidth: true
                                text: modelData.detail
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: logModel.count > 0

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.s

                    Label {
                        text: qsTr("服务器记录")
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
                                   : model.level === "warn" ? Enums.statusLevel.warningColor
                                   : model.level === "success" ? Enums.statusLevel.successColor
                                   : Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }

        }
    }

    Connections {
        target: page.backend
        function onLogMessage(text, level) {
            logModel.append({ "text": text, "level": level })
        }
    }

    ListModel { id: logModel }
}
