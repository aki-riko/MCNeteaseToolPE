// SPDX-License-Identifier: GPL-3.0-or-later
// Bedrock level.dat 与同世界 LevelDB/scriptData 编辑页面。
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import PrismQML

Item {
    id: page
    objectName: "levelDatPage"

    property var backend: null
    property string sourceUrl: ""
    property string pendingSourceUrl: ""
    property string errorMessage: ""
    property string noticeMessage: ""
    property var summary: ({})
    property var _changes: ({})
    property var _invalidChanges: ({})
    property var _dbChanges: ({})
    property var _invalidDbChanges: ({})
    property string activeSaveKind: ""
    readonly property bool busy: backend ? backend.busy : false
    readonly property int changeCount: Object.keys(_changes).length
    readonly property int invalidCount: Object.keys(_invalidChanges).length
    readonly property int dbChangeCount: Object.keys(_dbChanges).length
    readonly property int dbInvalidCount: Object.keys(_invalidDbChanges).length
    readonly property int totalChangeCount: changeCount + dbChangeCount

    function copiedMap(source) {
        var result = ({})
        for (var key in source) result[key] = source[key]
        return result
    }

    function displayedValue(token, originalValue) {
        var changed = page._changes[token]
        return changed === undefined ? originalValue : changed
    }

    function updateValue(token, originalValue, value, acceptable) {
        var changes = page.copiedMap(page._changes)
        var invalid = page.copiedMap(page._invalidChanges)
        if (value === String(originalValue)) {
            delete changes[token]
            delete invalid[token]
        } else {
            changes[token] = value
            if (acceptable) delete invalid[token]
            else invalid[token] = true
        }
        page._changes = changes
        page._invalidChanges = invalid
        page.errorMessage = ""
        if (filterInput.text !== "") filterTimer.restart()
    }

    function updateDbValue(token, originalValue, value, acceptable) {
        var changes = page.copiedMap(page._dbChanges)
        var invalid = page.copiedMap(page._invalidDbChanges)
        if (value === String(originalValue)) {
            delete changes[token]
            delete invalid[token]
        } else {
            changes[token] = value
            if (acceptable) delete invalid[token]
            else invalid[token] = true
        }
        page._dbChanges = changes
        page._invalidDbChanges = invalid
        page.errorMessage = ""
        if (filterInput.text !== "") filterTimer.restart()
    }

    function mapChangeList(source) {
        var tokens = Object.keys(source)
        tokens.sort()
        var result = []
        for (var index = 0; index < tokens.length; ++index) {
            var token = tokens[index]
            result.push({ "token": token, "value": source[token] })
        }
        return result
    }

    function changeList() { return page.mapChangeList(page._changes) }
    function dbChangeList() { return page.mapChangeList(page._dbChanges) }
    function allChangeList() { return page.changeList().concat(page.dbChangeList()) }

    function clearChanges() {
        page._changes = ({})
        page._invalidChanges = ({})
        page.errorMessage = ""
        if (filterInput.text !== "") filterTimer.restart()
    }

    function clearDbChanges() {
        page._dbChanges = ({})
        page._invalidDbChanges = ({})
        page.errorMessage = ""
        if (filterInput.text !== "") filterTimer.restart()
    }

    function clearAllChanges() {
        page.clearChanges()
        page.clearDbChanges()
    }

    function restoreRecentSource() {
        if (!backend || page.sourceUrl !== "" || page.busy) return
        var recentPath = String(backend.recentNbtPath || "")
        if (recentPath !== "") page.loadSourceNow(recentPath)
    }

    function nbtPathMenuItems() {
        var paths = backend ? (backend.savedNbtPaths || []) : []
        var items = []
        for (var index = 0; index < paths.length; ++index)
            items.push({ "text": String(paths[index]), "icon": "DocumentData" })
        return items
    }

    function selectSavedNbtPath(index) {
        var paths = backend ? (backend.savedNbtPaths || []) : []
        if (index < 0 || index >= paths.length) return
        page.requestLoad(String(paths[index]))
    }

    function loadSourceNow(url) {
        if (!backend || url === "") return
        page.sourceUrl = url
        page.errorMessage = ""
        page.noticeMessage = ""
        page.summary = ({})
        filterInput.text = ""
        filterTimer.stop()
        page.clearAllChanges()
        backend.load(page.sourceUrl)
    }

    function requestLoad(url) {
        if (url === "") return
        if (page.totalChangeCount > 0) {
            page.pendingSourceUrl = url
            discardDialog.open()
            return
        }
        page.loadSourceNow(url)
    }

    function requestSave() {
        if (page.changeCount === 0 || page.invalidCount > 0 || page.busy) return
        saveDialog.message = qsTr("将保存 %1 项修改，并把当前文件备份为 level.dat_old。是否继续？")
                             .arg(page.changeCount)
        saveDialog.open()
    }

    function saveChanges() {
        if (!backend || !page.summary.fingerprint) return
        page.errorMessage = ""
        page.noticeMessage = ""
        page.activeSaveKind = "nbt"
        backend.save(page.sourceUrl, String(page.summary.fingerprint), page.changeList())
    }

    function requestDbSave() {
        if (page.dbChangeCount === 0 || page.dbInvalidCount > 0 || page.busy) return
        dbSaveDialog.message = qsTr(
            "将保存 %1 项 scriptData 修改。请先关闭游戏中的这个世界；保存前会把完整 db 目录备份为 db_old（已存在则自动递增编号）。是否继续？"
        ).arg(page.dbChangeCount)
        dbSaveDialog.open()
    }

    function saveDbChanges() {
        if (!backend || !page.summary.extraDataFingerprint) return
        page.errorMessage = ""
        page.noticeMessage = ""
        page.activeSaveKind = "db"
        backend.saveExtraData(
            page.sourceUrl,
            String(page.summary.extraDataSequence),
            String(page.summary.extraDataFingerprint),
            page.dbChangeList()
        )
    }

    FileDialog {
        id: fileDialog
        title: qsTr("选择 level.dat")
        nameFilters: [qsTr("Minecraft 存档数据 (level.dat)"), qsTr("所有文件 (*)")]
        onAccepted: page.requestLoad(selectedFile.toString())
    }

    onBackendChanged: restoreRecentSource()
    Component.onCompleted: restoreRecentSource()

    Timer {
        id: filterTimer
        interval: Enums.duration.medium
        onTriggered: {
            if (page.backend)
                page.backend.setFilter(filterInput.text, page.allChangeList())
        }
    }

    Toast {
        parent: page
        message: page.noticeMessage
        severity: "success"
        closable: true
        duration: 5000
        position: Enums.notification.posBottom
        z: 99
        onMessageChanged: {
            if (message.length > 0) show()
            else if (visible) hide()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Enums.spacing.xxxl
        spacing: Enums.spacing.l

        Column {
            Layout.fillWidth: true
            spacing: Enums.spacing.xs

            Label {
                text: qsTr("世界存档数据编辑器")
                color: Enums.textColor.primary
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.displayLarge
                font.bold: true
            }
            Label {
                width: parent ? parent.width : 0
                text: qsTr("编辑 level.dat 的原版与网易 NBT，并编辑同级 db 中当前有效的 scriptData/ExtraData。NBT 保存前备份 level.dat_old；DB 保存前完整备份 db 目录。")
                textFormat: Text.PlainText
                color: Enums.textColor.secondary
                font.family: Enums.fontFamily
                font.pixelSize: Enums.typography.caption
                wrapMode: Text.WordWrap
            }
        }

        Card {
            Layout.fillWidth: true
            autoHeight: true

            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.l

                RowLayout {
                    width: parent ? parent.width : 0
                    spacing: Enums.spacing.m

                    LineEdit {
                        Layout.fillWidth: true
                        text: page.summary.filePath || page.sourceUrl
                        placeholderText: qsTr("尚未选择 level.dat")
                        readOnly: true
                    }
                    Button {
                        objectName: "levelDatBrowseButton"
                        text: qsTr("浏览")
                        feature: Enums.button.feature_split
                        menuItems: page.nbtPathMenuItems()
                        enabled: !page.busy
                        onClicked: fileDialog.open()
                        onMenuItemClicked: (index, _text) => page.selectSavedNbtPath(index)
                    }
                    Button {
                        text: page.busy ? qsTr("处理中…") : qsTr("重新读取")
                        style: Enums.button.style_primary
                        enabled: page.sourceUrl !== "" && !page.busy
                        onClicked: page.requestLoad(page.sourceUrl)
                    }
                }
                Label {
                    width: parent ? parent.width : 0
                    visible: page.errorMessage !== ""
                    text: page.errorMessage
                    textFormat: Text.PlainText
                    color: Enums.statusLevel.errorColor
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.bodySmall
                    wrapMode: Text.WordWrap
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Enums.spacing.m

            SegmentedControl {
                id: dataSelector
                objectName: "levelDatDataSelector"
                items: [
                    { "key": "nbt", "text": qsTr("Level.dat NBT") },
                    { "key": "db", "text": qsTr("世界数据库") }
                ]
            }
            Item { Layout.fillWidth: true }
            LineEdit {
                id: filterInput
                Layout.preferredWidth: 320
                placeholderText: dataSelector.currentIndex === 0
                                 ? qsTr("搜索 NBT 路径或值")
                                 : qsTr("搜索 ExtraData 路径或值")
                onTextChanged: filterTimer.restart()
            }
        }

        StackedWidget {
            id: dataStack
            objectName: "levelDatDataStack"
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: dataSelector.currentIndex
            animationEnabled: false

            Item {
                width: dataStack.width
                height: dataStack.height

                    Card {
                        id: nbtSummaryCard
                        anchors.top: parent.top
                        anchors.left: parent.left
                        anchors.right: parent.right
                        autoHeight: true
                        visible: page.summary.filePath !== undefined
                                 && page.summary.filePath !== ""

                        Column {
                            width: parent ? parent.width : 0
                            spacing: Enums.spacing.s

                            Label {
                                text: qsTr("Level.dat NBT")
                                color: Enums.textColor.primary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.subtitle
                                font.bold: true
                            }
                            Label {
                                width: parent ? parent.width : 0
                                text: qsTr("存档名：%1　格式：%2　文件：%3 字节　NBT：%4 字节")
                                      .arg(page.summary.levelName || qsTr("（未设置）"))
                                      .arg(page.summary.formatVersion)
                                      .arg(page.summary.fileSize)
                                      .arg(page.summary.declaredPayloadSize)
                                textFormat: Text.PlainText
                                color: Enums.textColor.secondary
                                font.family: Enums.fontFamily
                                font.pixelSize: Enums.typography.bodySmall
                                wrapMode: Text.WordWrap
                            }
                            RowLayout {
                                width: parent ? parent.width : 0
                                spacing: Enums.spacing.m

                                Label {
                                    Layout.fillWidth: true
                                    text: qsTr("根节点：%1　展开：%2　匹配：%3　网易标记：%4")
                                          .arg(page.summary.rootTagCount)
                                          .arg(page.summary.nbtNodeCount)
                                          .arg(page.backend ? page.backend.nbtTagModel.count : 0)
                                          .arg(page.summary.neteaseNodeCount)
                                    textFormat: Text.PlainText
                                    color: page.invalidCount > 0
                                           ? Enums.statusLevel.errorColor
                                           : Enums.textColor.secondary
                                    font.family: Enums.fontFamily
                                    font.pixelSize: Enums.typography.bodySmall
                                }
                                Button {
                                    text: qsTr("撤销全部")
                                    enabled: page.changeCount > 0 && !page.busy
                                    onClicked: page.clearChanges()
                                }
                                Button {
                                    text: page.busy ? qsTr("正在保存…") : qsTr("保存 %1 项修改").arg(page.changeCount)
                                    style: Enums.button.style_filled
                                    enabled: page.changeCount > 0
                                             && page.invalidCount === 0
                                             && !page.busy
                                    onClicked: page.requestSave()
                                }
                            }
                        }
                    }

                    LevelDatVirtualList {
                        id: nbtList
                        objectName: "levelDatNbtList"
                        anchors.top: nbtSummaryCard.visible
                                     ? nbtSummaryCard.bottom : parent.top
                        anchors.topMargin: nbtSummaryCard.visible ? Enums.spacing.m : 0
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        model: dataSelector.currentIndex === 0 && page.backend
                               ? page.backend.nbtTagModel : null
                        delegate: LevelDatTagDelegate {
                            changes: page._changes
                            scrollTarget: nbtList
                            totalCount: nbtList.count
                            onValueEdited: function(token, originalValue, value, acceptable) {
                                page.updateValue(token, originalValue, value, acceptable)
                            }
                        }
                    }
            }

            LevelDatExtraDataPane {
                objectName: "levelDatExtraDataPane"
                width: dataStack.width
                height: dataStack.height
                backend: dataSelector.currentIndex === 1 ? page.backend : null
                summary: page.summary
                changes: page._dbChanges
                changeCount: page.dbChangeCount
                invalidCount: page.dbInvalidCount
                busy: page.busy
                onValueEdited: function(token, originalValue, value, acceptable) {
                    page.updateDbValue(token, originalValue, value, acceptable)
                }
                onClearRequested: page.clearDbChanges()
                onSaveRequested: page.requestDbSave()
            }
        }
    }

    ConfirmDialog {
        id: saveDialog
        parent: page
        objectName: "levelDatSaveDialog"
        level: Enums.statusLevel.warning
        title: qsTr("保存 level.dat")
        messageAlignment: Text.AlignLeft
        confirmText: qsTr("保存")
        cancelText: qsTr("取消")
        onConfirmed: page.saveChanges()
    }

    ConfirmDialog {
        id: dbSaveDialog
        parent: page
        objectName: "levelDatDbSaveDialog"
        level: Enums.statusLevel.warning
        title: qsTr("保存世界数据库")
        messageAlignment: Text.AlignLeft
        confirmText: qsTr("备份并保存")
        cancelText: qsTr("取消")
        onConfirmed: page.saveDbChanges()
    }

    ConfirmDialog {
        id: discardDialog
        parent: page
        objectName: "levelDatDiscardDialog"
        level: Enums.statusLevel.warning
        title: qsTr("放弃未保存修改？")
        message: qsTr("当前有未保存的修改。继续读取会放弃这些修改。")
        confirmText: qsTr("放弃并读取")
        cancelText: qsTr("继续编辑")
        onConfirmed: {
            var target = page.pendingSourceUrl
            page.pendingSourceUrl = ""
            page.loadSourceNow(target)
        }
        onCancelled: page.pendingSourceUrl = ""
    }

    Connections {
        target: page.backend
        ignoreUnknownSignals: true

        function onLoaded(loadedSummary) {
            page.summary = loadedSummary
            if (page.activeSaveKind === "nbt") page.clearChanges()
            else if (page.activeSaveKind === "db") page.clearDbChanges()
            else page.clearAllChanges()
            page.errorMessage = ""
        }

        function onSaved(backupPath, message) {
            page.activeSaveKind = ""
            page.noticeMessage = String(message) + qsTr("；备份：") + String(backupPath)
        }

        function onExtraDataSaved(backupPath, message) {
            page.activeSaveKind = ""
            page.noticeMessage = String(message) + qsTr("；备份：") + String(backupPath)
        }

        function onExtraDataCopied(message) {
            page.noticeMessage = String(message)
        }

        function onFailed(message) {
            page.activeSaveKind = ""
            page.errorMessage = String(message)
        }
    }
}
