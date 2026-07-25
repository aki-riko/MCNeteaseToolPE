// SPDX-License-Identifier: GPL-3.0-or-later
// One-click project workflow 统一工程一键处理页面
// Cleanup -> read-only audit -> UUID rewrite -> automatic ZIP packaging.
// 垃圾清理 → 只读打包审核 → UUID 重写 → 自动输出 ZIP。
import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import PrismQML

Item {
    id: page

    property var backend: null
    property string projectDir: ""
    property string projectKind: ""
    property bool hasResult: false
    property bool passed: false
    property bool processingFailed: false
    property int errorCount: 0
    property int warningCount: 0
    property string resultMessage: ""
    readonly property bool busy: backend ? backend.busy : false

    FontMetrics {
        id: progressStatusFontMetrics
        font.family: Enums.fontFamily
        font.pixelSize: Enums.typography.body
    }

    function urlToPath(url) {
        var path = url.toString()
        path = path.replace(/^file:\/\/\//, "")
        return decodeURIComponent(path)
    }

    function formatProgress(value) {
        var numeric = Number(value)
        if (!isFinite(numeric)) numeric = 0
        var fixed = numeric.toFixed(2)
        return fixed.replace(/\.00$/, "").replace(/(\.\d)0$/, "$1") + "%"
    }

    function elideProgressStatus(value, availableWidth) {
        var status = value === null || value === undefined ? "" : String(value)
        return progressStatusFontMetrics.elidedText(
                    status, Text.ElideRight, Math.max(0, Number(availableWidth)))
    }

    function clearResult() {
        issueModel.clear()
        logModel.clear()
        hasResult = false
        passed = false
        processingFailed = false
        errorCount = 0
        warningCount = 0
        resultMessage = ""
    }

    function refreshProjectKind() {
        projectKind = backend && projectDir !== ""
                      ? backend.classifyProject(projectDir) : ""
    }

    function restoreRecentProjectDir() {
        if (!backend || projectDir !== "") return
        var recentPath = String(backend.recentProjectPath || "")
        if (recentPath !== "") projectDir = recentPath
    }

    function projectPathMenuItems() {
        var paths = backend ? (backend.savedProjectPaths || []) : []
        var items = []
        for (var index = 0; index < paths.length; ++index)
            items.push({ "text": String(paths[index]), "icon": "FolderOpen" })
        return items
    }

    function selectSavedProjectPath(index) {
        var paths = backend ? (backend.savedProjectPaths || []) : []
        if (index < 0 || index >= paths.length) return
        page.projectDir = String(paths[index])
    }

    onProjectDirChanged: {
        clearResult()
        if (backend && projectDir !== "") backend.rememberProjectPath(projectDir)
        if (backend) backend.reset()
        refreshProjectKind()
    }
    onBackendChanged: {
        restoreRecentProjectDir()
        refreshProjectKind()
    }

    Component.onCompleted: restoreRecentProjectDir()

    FolderDialog {
        id: folderDialog
        title: qsTr("选择网易 MC 工程目录")
        onAccepted: page.projectDir = page.urlToPath(selectedFolder)
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
                        text: qsTr("工程处理")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.displayLarge
                        font.bold: true
                    }
                    HintIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: Enums.iconSize.m
                        toolTipText: qsTr("一键依次清理垃圾、执行只读打包审核；审核通过后重写 UUID 并自动输出 ZIP。任一步失败都会停止。")
                    }
                }

                Label {
                    width: parent ? parent.width : 0
                    text: qsTr("选择工程后只需点击一次，工具会自动清理、审核、重写 UUID，并在审核通过后输出 ZIP。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    wrapMode: Text.WordWrap
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Row {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.s

                        Label {
                            objectName: "projectTitle"
                            text: qsTr("当前工程")
                            color: Enums.textColor.primary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.subtitle
                            font.bold: true
                        }

                        Tag {
                            objectName: "projectTypeTag"
                            visible: page.projectKind !== ""
                            text: page.projectKind === "map" ? qsTr("地图") : qsTr("Add-ons")
                            status: page.projectKind === "map"
                                    ? Enums.statusLevel.info : Enums.statusLevel.success
                        }
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        spacing: Enums.spacing.m

                        LineEdit {
                            Layout.fillWidth: true
                            text: page.projectDir
                            placeholderText: qsTr("请选择网易 MC 工程目录")
                            readOnly: true
                        }

                        Button {
                            objectName: "projectPathBrowseButton"
                            text: page.projectDir === "" ? qsTr("选择目录") : qsTr("更换目录")
                            style: page.projectDir === "" ? Enums.button.style_primary : Enums.button.style_default
                            feature: Enums.button.feature_split
                            menuItems: page.projectPathMenuItems()
                            enabled: !page.busy
                            onClicked: folderDialog.open()
                            onMenuItemClicked: (index, _text) => page.selectSavedProjectPath(index)
                        }
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.l

                    Label {
                        text: qsTr("一键处理并审核")
                        color: Enums.textColor.primary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.subtitle
                        font.bold: true
                    }

                    Label {
                        width: parent ? parent.width : 0
                        text: qsTr("1  垃圾清理   →   2  打包审核   →   3  UUID 重写   →   4  自动输出 ZIP")
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.bodySmall
                        wrapMode: Text.WordWrap
                    }

                    Button {
                        objectName: "oneClickRunButton"
                        width: page.busy && parent ? parent.width : implicitWidth
                        clip: true
                        contentAlignment: Enums.button.align_left
                        text: qsTr("一键处理并审核")
                        loading: page.busy
                        loadingText: page.elideProgressStatus(
                                         backend ? backend.status : "",
                                         width - iconSize - Enums.spacing.s
                                         - Enums.spacing.m * 2)
                        style: Enums.button.style_primary
                        enabled: page.projectDir !== "" && backend !== null
                        onClicked: {
                            page.clearResult()
                            backend.run(page.projectDir)
                        }
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: page.busy || (backend && backend.progress > 0) || logModel.count > 0

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    RowLayout {
                        width: parent ? parent.width : 0

                        Label {
                            objectName: "pipelineStatusText"
                            Layout.fillWidth: true
                            visible: !backend || backend.archivePath === ""
                            type: Enums.label.type_body_strong
                            text: backend ? backend.status : qsTr("准备开始")
                            customTextColor: backend && backend.phase === "failed"
                                             ? Enums.statusLevel.errorColor
                                             : Enums.textColor.primary
                            wrapMode: Text.NoWrap
                            elide: Text.ElideRight
                            maximumLineCount: 1
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: backend && backend.archivePath !== ""
                            spacing: Enums.spacing.xxs

                            Label {
                                type: Enums.label.type_body_strong
                                text: qsTr("全部完成：审核通过，ZIP 已输出到")
                            }

                            Label {
                                objectName: "pipelineArchiveLink"
                                Layout.fillWidth: true
                                type: Enums.label.type_hyperlink
                                text: backend ? backend.archivePath : ""
                                wrapMode: Text.WrapAnywhere
                                onClicked: backend.revealArchive()
                            }
                        }

                        Label {
                            objectName: "pipelineProgressText"
                            text: page.formatProgress(backend ? backend.progress : 0)
                            color: Enums.textColor.secondary
                            font.family: Enums.fontFamily
                            font.pixelSize: Enums.typography.caption
                        }
                    }

                    ProgressBar {
                        objectName: "pipelineProgress"
                        width: parent ? parent.width : 0
                        from: 0
                        to: 100
                        value: backend ? backend.progress : 0
                        error: backend ? backend.phase === "failed" : false
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: page.hasResult

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: page.processingFailed ? qsTr("处理失败")
                              : page.passed ? qsTr("审核通过") : qsTr("审核未通过")
                        color: page.passed ? Enums.statusLevel.successColor : Enums.statusLevel.errorColor
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.titleLarge
                        font.bold: true
                    }
                    Label {
                        objectName: "resultMessageText"
                        width: parent ? parent.width : 0
                        visible: !backend || backend.archivePath === ""
                        type: Enums.label.type_body_small
                        text: page.resultMessage
                        customTextColor: Enums.textColor.secondary
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        width: parent ? parent.width : 0
                        visible: backend && backend.archivePath !== ""
                        spacing: Enums.spacing.xxs

                        Label {
                            type: Enums.label.type_body_small
                            text: qsTr("全部完成：审核通过，ZIP 已输出到")
                        }

                        Label {
                            objectName: "resultArchiveLink"
                            Layout.fillWidth: true
                            type: Enums.label.type_hyperlink
                            text: backend ? backend.archivePath : ""
                            wrapMode: Text.WrapAnywhere
                            onClicked: backend.revealArchive()
                        }
                    }
                    Label {
                        visible: !page.processingFailed
                        text: qsTr("错误 %1 · 警告 %2").arg(page.errorCount).arg(page.warningCount)
                        color: Enums.textColor.secondary
                        font.family: Enums.fontFamily
                        font.pixelSize: Enums.typography.caption
                    }
                }
            }

            Card {
                width: parent ? parent.width : 0
                autoHeight: true
                visible: issueModel.count > 0

                Column {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    Label {
                        text: qsTr("审核问题（%1 项）").arg(issueModel.count)
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
                            Label {
                                width: parent ? parent.width : 0
                                text: model.codeName + " · " + model.title
                                color: model.severity === "error" ? Enums.statusLevel.errorColor
                                       : model.severity === "warning" ? Enums.statusLevel.warningColor
                                       : Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.body
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Label {
                                width: parent ? parent.width : 0
                                text: model.detail + (model.path === "" ? "" : "\n" + model.path)
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.caption
                                wrapMode: Text.WrapAnywhere
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
                        text: qsTr("处理记录")
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
        function onFinished(passed, errors, warnings, issues, message) {
            page.hasResult = true
            page.passed = passed
            page.processingFailed = backend.phase === "failed"
            page.errorCount = errors
            page.warningCount = warnings
            page.resultMessage = message
            issueModel.clear()
            for (var i = 0; i < issues.length; ++i) {
                issueModel.append({
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
