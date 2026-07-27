// SPDX-License-Identifier: GPL-3.0-or-later
// 打包审核页面
// 绑定 per-page 后端 backend:扫描网易 MC 工程中可本地确定的公开机审规则。
// 流程:选择目录 → audit(dir) → finished(passed,errorCount,warningCount,issues)。
import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import PrismQML

Item {
    id: page

    // AsyncQmlPage 注入的 per-page 后端对象(host 通过 setSource 初始属性赋值)
    property var backend: null

    property string projectDir: ""
    property bool hasResult: false
    property bool passed: false
    property int errorCount: 0
    property int warningCount: 0
    property bool embedded: false

    function urlToPath(url) {
        var s = url.toString()
        s = s.replace(/^file:\/\/\//, "")
        return decodeURIComponent(s)
    }

    onProjectDirChanged: {
        if (!page.embedded) return
        issueModel.clear()
        logModel.clear()
        page.hasResult = false
        page.passed = false
        page.errorCount = 0
        page.warningCount = 0
    }

    FolderDialog {
        id: folderDialog
        title: qsTr("选择要审核的工程目录")
        onAccepted: {
            page.projectDir = urlToPath(selectedFolder)
            issueModel.clear()
            logModel.clear()
            page.hasResult = false
            backend.audit(page.projectDir)
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
                        text: qsTr("打包审核")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.displayLarge
                        font.bold: true
                    }
                    HintIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: 18
                        toolTipText: qsTr("检查网易已公开且能从工程内容确定的机审阻断项。\n审核前会自动补全行为包 entities 与资源包 textures；结果按严重程度分级并附定位信息。")
                    }
                }
                Label {
                    text: qsTr("检查可在本地确定的网易公开规则，提前发现上架阻断问题。")
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
                        text: qsTr("只读模拟网易打包机审，检查工程结构、资源规范与 Python 语义错误。")
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
                            objectName: "auditStartButton"
                            text: qsTr("开始审核")
                            style: Enums.button.style_primary
                            enabled: page.projectDir !== "" && !backend.busy
                            onClicked: {
                                issueModel.clear()
                                page.hasResult = false
                                backend.audit(page.projectDir)
                            }
                        }
                    }
                }
            }

            // 摘要
            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: page.hasResult
                Row {
                    spacing: Enums.spacing.xxl
                    Column {
                        spacing: Enums.spacing.xs
                        Label {
                            text: page.passed ? qsTr("通过") : qsTr("未通过")
                            color: page.passed ? Enums.statusLevel.successColor : Enums.statusLevel.errorColor
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.titleLarge
                            font.bold: true
                        }
                        Label {
                            text: qsTr("审核结果")
                            color: Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                        }
                    }
                    Column {
                        spacing: Enums.spacing.xs
                        Label {
                            text: page.errorCount
                            color: Enums.statusLevel.errorColor
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.titleLarge
                            font.bold: true
                        }
                        Label {
                            text: qsTr("错误")
                            color: Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                        }
                    }
                    Column {
                        spacing: Enums.spacing.xs
                        Label {
                            text: page.warningCount
                            color: Enums.statusLevel.warningColor
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.titleLarge
                            font.bold: true
                        }
                        Label {
                            text: qsTr("警告")
                            color: Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                        }
                    }
                }
            }

            // 问题列表
            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: issueModel.count > 0
                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m
                    Label {
                        text: qsTr("问题明细 (") + issueModel.count + qsTr(" 项)")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Repeater {
                        model: issueModel
                        delegate: Column {
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.xs
                            // 严重程度使用 PrismQML 统一徽章，随皮肤自动适配颜色与边框。
                            Row {
                                width: parent ? parent.width : 0
                                spacing: Enums.spacing.s
                                Badge {
                                    id: sevBadge
                                    anchors.verticalCenter: parent.verticalCenter
                                    level: model.severity === "error" ? Enums.statusLevel.error
                                         : model.severity === "warning" ? Enums.statusLevel.warning
                                         : Enums.statusLevel.info
                                    text: model.severity === "error" ? qsTr("错误")
                                        : model.severity === "warning" ? qsTr("警告")
                                        : qsTr("提示")
                                }
                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: model.codeName + " (code " + model.code + ")"
                                    color: Enums.textColor.primary
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.body
                                    font.bold: true
                                }
                            }
                            Label {
                                width: parent ? parent.width : 0
                                text: model.title
                                color: Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                                wrapMode: Text.WordWrap
                            }
                            Label {
                                width: parent ? parent.width : 0
                                text: model.detail
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                                wrapMode: Text.WordWrap
                                visible: model.detail !== ""
                            }
                            Label {
                                width: parent ? parent.width : 0
                                text: model.path
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.NoWrap
                                elide: Text.ElideMiddle
                                visible: model.path !== ""
                            }
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
        function onFinished(passed, errorCount, warningCount, issues) {
            page.hasResult = true
            page.passed = passed
            page.errorCount = errorCount
            page.warningCount = warningCount
            issueModel.clear()
            for (var i = 0; i < issues.length; ++i) {
                issueModel.append({
                    "code": issues[i].code,
                    "codeName": issues[i].codeName,
                    "severity": issues[i].severity,
                    "title": issues[i].title,
                    "detail": issues[i].detail,
                    "path": issues[i].path
                })
            }
        }
    }

    ListModel { id: issueModel }
    ListModel { id: logModel }
}
