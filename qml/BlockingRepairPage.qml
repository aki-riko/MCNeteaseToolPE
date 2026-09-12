// SPDX-License-Identifier: GPL-3.0-or-later
// 非代码阻塞项的预览、确认修复与自动复审页面。
import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import PrismQML

Item {
    id: root
    objectName: "blockingRepairPage"

    property var backend: null
    property string projectDir: ""
    property bool syncingProjectPath: false
    property var repairState: backend ? (backend.state || {}) : ({})
    readonly property bool busy: backend ? backend.busy === true : false
    readonly property bool canUndo: backend ? backend.canUndo === true : false
    readonly property bool hasInspection: repairState.rootPath !== ""
    readonly property int repairableCount: Number(repairState.repairableCount || 0)
    readonly property int auditErrorCount: Number(repairState.auditErrorCount || 0)
    readonly property int auditWarningCount: Number(repairState.auditWarningCount || 0)
    readonly property bool fromProjectWorkflow: repairState.source === "projectWorkflow"

    function urlToPath(url) {
        var path = url.toString()
        path = path.replace(/^file:\/\/\//, "")
        return decodeURIComponent(path)
    }

    function inspectProject() {
        if (backend && projectDir !== "") backend.inspect(projectDir)
    }

    function syncBackendProjectPath() {
        if (!backend) return
        var path = String(backend.projectPath || "")
        if (path === "" || path === projectDir) return
        syncingProjectPath = true
        projectDir = path
        syncingProjectPath = false
    }

    function confirmRepair(item) {
        if (!item || !item.id) return
        repairDialog.repairId = String(item.id)
        repairDialog.repairTitle = String(item.title || "")
        repairDialog.repairChange = String(item.change || "")
        repairDialog.repairDestructive = item.destructive === true
        repairDialog.repairImpact = String(item.impact || "")
        repairDialog.open()
    }

    onProjectDirChanged: {
        if (backend && !syncingProjectPath) backend.reset()
    }
    onBackendChanged: syncBackendProjectPath()
    Component.onCompleted: syncBackendProjectPath()

    FolderDialog {
        id: folderDialog
        title: qsTr("选择网易 MC 工程目录")
        onAccepted: root.projectDir = root.urlToPath(selectedFolder)
    }

    Connections {
        target: root.backend
        ignoreUnknownSignals: true

        function onResult(result) {
            if (!result || !result.message) return
            resultToast.show(
                        String(result.message),
                        result.success === true ? "success" : "error")
        }

        function onProjectPathChanged() {
            root.syncBackendProjectPath()
        }

        function onAuditResultAdopted(_projectPath) {
            root.syncBackendProjectPath()
        }
    }

    Toast {
        id: resultToast
        parent: root
        severity: "info"
        closable: false
        duration: 3000
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

                Row {
                    spacing: Enums.spacing.s

                    Label {
                        text: qsTr("阻塞项修复")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.displayLarge
                        font.bold: true
                    }
                    HintIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: Enums.iconSize.m
                        toolTipText: qsTr("仅处理能从工程内容确定的非代码问题。每项写入的影响会在确认前明确展示，完成后自动复审。")
                    }
                }

                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("工程处理审核失败时会自动带入真实阻塞项；也可手动检查工程。代码、未知编码、路径重命名和无法确定的兼容性问题只会保留定位，不会擅自修改。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }

            Card {
                objectName: "blockingRepairProjectCard"
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("工程目录")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        LineEdit {
                            Layout.fillWidth: true
                            text: root.projectDir
                            placeholderText: qsTr("请选择网易 MC 工程目录")
                            readOnly: true
                        }

                        Button {
                            objectName: "blockingRepairBrowseButton"
                            text: root.projectDir === "" ? qsTr("选择目录") : qsTr("更换目录")
                            style: root.projectDir === "" ? Enums.button.style_primary
                                                           : Enums.button.style_default
                            enabled: !root.busy
                            onClicked: folderDialog.open()
                        }
                    }
                }
            }

            Card {
                objectName: "blockingRepairInspectCard"
                width: parent ? parent.width : 0
                autoHeight: true

                RowLayout {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.l

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Enums.spacing.xxs

                        Label {
                            Layout.fillWidth: true
                            text: root.busy ? qsTr("正在检查工程")
                                            : String(root.repairState.message || qsTr("尚未检查工程"))
                            color: root.repairState.phase === "failed"
                                   ? Enums.statusLevel.errorColor : Enums.textColor.primary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.body
                            font.bold: true
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: root.fromProjectWorkflow
                                  ? qsTr("已接收工程处理的真实审核结果；修复候选只会基于该工程当前状态生成。")
                                  : qsTr("检查过程不会写入工程；修复按钮只在可验证的项目上显示。")
                            color: Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                            wrapMode: Text.WordWrap
                        }
                    }

                    Button {
                        objectName: "blockingRepairInspectButton"
                        text: root.fromProjectWorkflow ? qsTr("重新检查") : qsTr("检查")
                        loading: root.busy
                        style: Enums.button.style_primary
                        enabled: root.projectDir !== "" && !root.busy
                        onClicked: root.inspectProject()
                    }

                    Button {
                        objectName: "blockingRepairUndoButton"
                        visible: root.canUndo
                        text: qsTr("撤销上次清理")
                        style: Enums.button.style_default
                        enabled: !root.busy
                        onClicked: {
                            if (root.backend) root.backend.undoLastRemoval()
                        }
                    }
                }
            }

            Card {
                objectName: "blockingRepairSummaryCard"
                width: parent ? parent.width : 0
                autoHeight: true
                visible: root.hasInspection

                RowLayout {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.xl

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Enums.spacing.xxs

                        Label {
                            Layout.fillWidth: true
                            text: root.repairState.rootPath || ""
                            color: Enums.textColor.tertiary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                            wrapMode: Text.NoWrap
                            elide: Text.ElideMiddle
                        }
                        Label {
                            objectName: "blockingRepairWorkflowSourceLabel"
                            Layout.fillWidth: true
                            visible: root.fromProjectWorkflow
                            text: qsTr("来自最近一次工程处理审核")
                            color: Enums.statusLevel.infoColor
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("可自动优化 %1 项 · 审核错误 %2 · 警告 %3")
                                  .arg(root.repairableCount)
                                  .arg(root.auditErrorCount)
                                  .arg(root.auditWarningCount)
                            color: Enums.textColor.primary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.body
                            font.bold: true
                            wrapMode: Text.WordWrap
                        }
                    }

                    Badge {
                        objectName: "blockingRepairSummaryBadge"
                        text: root.repairableCount > 0 ? qsTr("可修复")
                                                       : root.auditErrorCount > 0 ? qsTr("需处理")
                                                                                 : qsTr("正常")
                        level: root.repairableCount > 0 ? Enums.statusLevel.success
                              : root.auditErrorCount > 0 ? Enums.statusLevel.warning
                                                          : Enums.statusLevel.info
                    }
                }
            }

            Card {
                objectName: "blockingRepairItemsCard"
                width: parent ? parent.width : 0
                autoHeight: true
                visible: root.hasInspection && root.repairableCount > 0

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("可自动优化项（%1 项）").arg(root.repairableCount)
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }

                    Repeater {
                        model: root.repairState.items || []

                        delegate: RowLayout {
                            required property var modelData
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.m

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Enums.spacing.xxs

                                RowLayout {
                                    spacing: Enums.spacing.s
                                    Badge {
                                        objectName: "blockingRepairActionBadge_" + modelData.id
                                        text: modelData.destructive === true
                                              ? qsTr("隔离清理") : qsTr("可修复")
                                        level: modelData.destructive === true
                                               ? Enums.statusLevel.warning
                                               : Enums.statusLevel.success
                                    }
                                    Label {
                                        text: modelData.title || ""
                                        color: Enums.textColor.primary
                                        font.family: Enums.fontFamily
                                        font.pixelSize: Enums.typography.body
                                        font.bold: true
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.detail || ""
                                    color: Enums.textColor.secondary
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.caption
                                    wrapMode: Text.WordWrap
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: (modelData.change || "")
                                          + (modelData.path ? "\n" + modelData.path : "")
                                    color: Enums.textColor.tertiary
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.caption
                                    wrapMode: Text.WrapAnywhere
                                }
                                Label {
                                    Layout.fillWidth: true
                                    visible: String(modelData.impact || "") !== ""
                                    text: qsTr("影响：%1").arg(modelData.impact || "")
                                    color: Enums.statusLevel.warningColor
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.caption
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Button {
                                objectName: "blockingRepairApplyButton_" + modelData.id
                                text: modelData.destructive === true
                                      ? qsTr("隔离清理") : qsTr("修复")
                                style: Enums.button.style_filled
                                level: modelData.destructive === true
                                       ? Enums.statusLevel.warning
                                       : Enums.statusLevel.info
                                enabled: !root.busy
                                onClicked: root.confirmRepair(modelData)
                            }
                        }
                    }
                }
            }

            Card {
                objectName: "blockingRepairRemainingCard"
                width: parent ? parent.width : 0
                autoHeight: true
                visible: root.hasInspection && root.auditErrorCount > 0

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("仍需手动处理（%1 项）").arg(root.auditErrorCount)
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }
                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("以下仅展示前 8 项。代码、未知配置和可能影响兼容性的内容不会被自动修改。")
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }

                    Repeater {
                        model: root.repairState.blockingPreview || []

                        delegate: Column {
                            required property int index
                            required property var modelData
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.xxs

                            Label {
                                width: parent ? parent.width : 0
                                text: (modelData.codeName || qsTr("静态检查"))
                                      + " · " + (modelData.title || "")
                                color: Enums.statusLevel.errorColor
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Label {
                                width: parent ? parent.width : 0
                                text: (modelData.detail || "")
                                      + (modelData.path ? "\n" + modelData.path : "")
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.WrapAnywhere
                            }
                            Label {
                                objectName: "blockingRepairGuidance_" + index
                                width: parent ? parent.width : 0
                                visible: String(modelData.guidance || "") !== ""
                                text: qsTr("处理建议：%1").arg(modelData.guidance || "")
                                color: Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                    Label {
                        width: parent ? parent.width : 0
                        visible: root.repairState.blockingPreviewTruncated === true
                        text: qsTr("其余问题可在“工程处理”的完整审核结果中查看。")
                        color: Enums.textColor.tertiary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Label {
                objectName: "blockingRepairEmptyState"
                width: parent ? parent.width : 0
                visible: root.hasInspection && root.repairableCount === 0
                         && root.auditErrorCount === 0
                text: qsTr("工程未发现可自动优化的阻塞项。")
                color: Enums.textColor.secondary
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.body
                wrapMode: Text.WordWrap
            }
        }
    }

    ConfirmDialog {
        id: repairDialog
        parent: root
        objectName: "blockingRepairConfirmDialog"
        property string repairId: ""
        property string repairTitle: ""
        property string repairChange: ""
        property string repairImpact: ""
        property bool repairDestructive: false
        level: repairDestructive ? Enums.statusLevel.warning
                                 : Enums.statusLevel.warning
        title: repairDestructive ? qsTr("确认隔离清理") : qsTr("确认修复")
        message: repairTitle + "\n\n" + repairChange
                 + (repairImpact === "" ? "" : qsTr("\n\n影响：%1").arg(repairImpact))
                 + (repairDestructive
                    ? qsTr("\n\n此操作会将对应文件或目录移入工程外隔离区，可在本页撤销上次清理。执行后将立即重新审核工程。")
                    : qsTr("\n\n执行后将立即重新审核工程。"))
        messageAlignment: Text.AlignLeft
        confirmText: repairDestructive ? qsTr("隔离清理") : qsTr("执行修复")
        cancelText: qsTr("取消")
        onConfirmed: {
            if (root.backend && repairId !== "") root.backend.applyRepair(repairId)
        }
    }
}
