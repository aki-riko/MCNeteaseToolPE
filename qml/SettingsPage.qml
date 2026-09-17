// SPDX-License-Identifier: GPL-3.0-or-later
// 设置页面
// 自动更新入口:只提供宿主配置并调用引擎门面，使用 PrismQML 默认右下角 Toast。
import QtQuick
import QtQuick.Window
import PrismQML

Item {
    id: page

    // AsyncQmlPage 为所有页面统一传入的占位属性 / placeholder accepted by AsyncQmlPage
    property var backend: null

    // 云母效果开关需要直接调用引擎窗口的 QML 方法。
    readonly property var parentWindow: Window.window

    function iconPath(name) {
        return Enums.iconPath + name + ".svg"
    }

    AutoUpdater {
        id: autoUpdater
        updater: appUpdater
        silentArgs: appInstallerSilentArgs
        notifyWhenUpToDate: true
    }

    ScrollArea {
        id: scroll
        anchors.fill: parent
        padding: Enums.spacing.xxxl

        Column {
            width: parent ? parent.width : 0
            spacing: Enums.spacing.xxl

            // 标题
            Column {
                width: parent ? parent.width : 0
                spacing: Enums.spacing.xs
                Label {
                    text: qsTr("设置")
                    color: Enums.textColor.primary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.displayLarge
                    font.bold: true
                }
                Label {
                    text: qsTr("审核性能、外观、窗口与自动更新。")
                    color: Enums.textColor.secondary
                    font.family: Enums.fontFamily
                    font.pixelSize: Enums.typography.caption
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }

            // Python 2.7 审核并发
            SettingsCardGroup {
                width: parent ? parent.width : 0
                title: qsTr("审核性能")

                SettingsCardCore {
                    width: parent ? parent.width : 0
                    icon: page.iconPath("DeveloperBoard")
                    title: qsTr("Python 2.7 审核并发数")
                    content: backend && backend.environmentOverrideActive
                             ? qsTr("启动环境正在覆盖为 %1 路，界面设置暂不可修改。")
                                   .arg(backend.environmentOverrideValue)
                             : qsTr("范围 1–%1；修改后从下一次审核开始生效。")
                                   .arg(backend ? backend.logicalProcessorCount : 1)
                    disabled: backend === null || backend.environmentOverrideActive

                    SpinBox {
                        id: workerSpin
                        objectName: "python27WorkersSpinBox"
                        minimum: 1
                        maximum: backend ? backend.logicalProcessorCount : 1
                        stepSize: 1
                        decimals: 0
                        suffix: qsTr(" 路")
                        value: backend ? backend.python27Workers : 1
                        enabled: backend !== null && !backend.environmentOverrideActive
                        onValueModified: function(newValue) {
                            if (backend && !backend.setPython27Workers(Math.round(newValue))) {
                                workerSpin.setValue(backend.python27Workers)
                            }
                        }
                    }
                }
            }

            // 外观设置(移植自 PrismQML Gallery):主题与皮肤由引擎即时应用。
            SettingsCardGroup {
                width: parent ? parent.width : 0
                title: qsTr("外观")

                // 应用主题
                SettingsCard {
                    readonly property var themeValues:
                        ConfigManager ? ConfigManager.themeOptions : []

                    objectName: "themeSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("DarkTheme")
                    title: qsTr("应用主题")
                    content: qsTr("切换浅色 / 深色主题，或跟随系统。")
                    type: Enums.settingCard.type_combobox
                    model: [
                        Translator.tr("gallery_217cfe7db1e3d10a"),
                        Translator.tr("gallery_aa0819dfc4d8d782"),
                        Translator.tr("gallery_a6b75d0680322a61")
                    ]
                    currentIndex: {
                        var idx = themeValues.indexOf(
                            ConfigManager ? ConfigManager.theme : "auto")
                        return idx >= 0 ? idx : 0
                    }
                    onIndexSelected: function(idx) {
                        if (ConfigManager && idx >= 0 && idx < themeValues.length) {
                            ConfigManager.setTheme(themeValues[idx])
                        }
                    }
                }

                // 主题色
                SettingsCard {
                    objectName: "accentColorSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("Color")
                    title: qsTr("主题色")
                    content: qsTr("选择默认或自定义颜色。")
                    type: Enums.settingCard.type_color
                    defaultColor: Enums.accentDefaults.accent
                    customColor: ConfigManager
                                 ? ConfigManager.accentColor
                                 : Enums.accentColor
                    useCustomColor: customColor.toString().toLowerCase()
                                    !== defaultColor.toString().toLowerCase()
                    defaultColorText: Translator.tr("gallery_af76608af89e9682")
                    customColorText: Translator.tr("gallery_781b07fdcb56b56a")
                    chooseColorText: Translator.tr("gallery_369b82fa0700db02")
                    onCustomColorPicked: function(c) {
                        if (ConfigManager) {
                            ConfigManager.setAccentColor(c.toString())
                        }
                    }
                }

                // 设计皮肤
                SettingsCard {
                    readonly property var skinValues:
                        ConfigManager ? ConfigManager.skinOptions : []

                    objectName: "skinSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("Color")
                    title: qsTr("设计皮肤")
                    content: qsTr("切换应用的设计风格。")
                    type: Enums.settingCard.type_combobox
                    model: [
                        Translator.tr("skin_fluent_design"),
                        Translator.tr("skin_neobrutalism"),
                        Translator.tr("skin_vintage_ticket"),
                        Translator.tr("skin_neumorphism")
                    ]
                    currentIndex: {
                        var idx = skinValues.indexOf(
                            ConfigManager ? ConfigManager.skin : "fluent")
                        return idx >= 0 ? idx : 0
                    }
                    onIndexSelected: function(idx) {
                        if (ConfigManager && idx >= 0 && idx < skinValues.length) {
                            ConfigManager.setSkin(skinValues[idx])
                        }
                    }
                }
            }

            // 窗口行为(移植自 PrismQML Gallery):DPI 与懒加载重启后生效。
            SettingsCardGroup {
                width: parent ? parent.width : 0
                title: qsTr("窗口")

                // DPI 缩放
                SettingsCard {
                    readonly property var dpiValues:
                        ConfigManager ? ConfigManager.dpiScaleOptions : []

                    objectName: "dpiScaleSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("ResizeImage")
                    title: qsTr("DPI 缩放")
                    content: qsTr("修改后重启应用生效。")
                    type: Enums.settingCard.type_combobox
                    model: dpiValues.map(function(value) {
                        return value === 0
                            ? Translator.tr("gallery_217cfe7db1e3d10a")
                            : value + "%"
                    })
                    currentIndex: {
                        var idx = dpiValues.indexOf(
                            ConfigManager ? ConfigManager.dpiScale : 0)
                        return idx >= 0 ? idx : 0
                    }
                    onIndexSelected: function(idx) {
                        if (ConfigManager && idx >= 0 && idx < dpiValues.length) {
                            ConfigManager.setDpiScale(dpiValues[idx])
                        }
                    }
                }

                // 关闭时的行为
                SettingsCard {
                    readonly property var closeActionValues: ["tray", "quit"]

                    objectName: "closeActionSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("ArrowExit")
                    title: qsTr("关闭时的行为")
                    content: qsTr("点击关闭按钮时隐藏到托盘，或直接退出程序。")
                    type: Enums.settingCard.type_combobox
                    model: [qsTr("关闭到托盘"), qsTr("退出程序")]
                    currentIndex: {
                        var idx = closeActionValues.indexOf(
                            backend ? backend.closeAction : "tray")
                        return idx >= 0 ? idx : 0
                    }
                    onIndexSelected: function(idx) {
                        if (backend && idx >= 0 && idx < closeActionValues.length) {
                            backend.setCloseAction(closeActionValues[idx])
                        }
                    }
                }

                // 云母效果
                SettingsCard {
                    objectName: "micaSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("Blur")
                    title: qsTr("云母效果")
                    content: qsTr("Windows 11 窗口云母背景；其他系统不可用。")
                    type: Enums.settingCard.type_switch
                    checked: ConfigManager ? ConfigManager.micaEnabled : false
                    onSwitchToggled: function(isChecked) {
                        if (page.parentWindow
                                && page.parentWindow.setMicaEffectEnabled) {
                            page.parentWindow.setMicaEffectEnabled(isChecked)
                        }
                        if (ConfigManager) {
                            ConfigManager.setMicaEnabled(isChecked)
                        }
                    }
                }

                // DWM 原生阴影
                SettingsCard {
                    objectName: "dwmShadowSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("SquareShadow")
                    title: qsTr("DWM 原生阴影")
                    content: qsTr("Windows 原生窗口阴影。")
                    type: Enums.settingCard.type_switch
                    checked: ConfigManager ? ConfigManager.dwmShadow : true
                    onSwitchToggled: function(isChecked) {
                        if (ConfigManager) {
                            ConfigManager.setDwmShadow(isChecked)
                        }
                    }
                }

                // 懒加载
                SettingsCard {
                    objectName: "lazyLoadingSettingsCard"
                    width: parent ? parent.width : 0
                    icon: page.iconPath("Timer")
                    title: qsTr("懒加载")
                    content: qsTr("延迟加载页面内容；修改后重启应用生效。")
                    type: Enums.settingCard.type_switch
                    checked: ConfigManager ? ConfigManager.lazyLoading : true
                    onSwitchToggled: function(isChecked) {
                        if (ConfigManager) {
                            ConfigManager.setLazyLoading(isChecked)
                        }
                    }
                }
            }

            // 自动更新卡片
            SettingsCardGroup {
                width: parent ? parent.width : 0
                title: qsTr("自动更新")

                SettingsCard {
                    width: parent ? parent.width : 0
                    icon: page.iconPath("ArrowSync")
                    title: qsTr("检查更新")
                    content: qsTr("检查 GitHub 发布的新版本；发现新版将确认后自动下载并静默安装重启。")
                    type: Enums.settingCard.type_primary_push
                    buttonText: qsTr("检查更新")
                    onClicked: autoUpdater.check()
                }
            }

            // 关于卡片
            SettingsCardGroup {
                width: parent ? parent.width : 0
                title: qsTr("关于")

                Item {
                    id: aboutCardHost
                    width: parent ? parent.width : 0
                    implicitHeight: Enums.settingCard.height_with_content
                    height: implicitHeight

                    SettingsCardCore {
                        objectName: "aboutSettingsCard"
                        anchors.fill: parent
                        icon: page.iconPath("Info")
                        // 保留有描述的标准卡片高度；文字由上层组合，支持行内超链接。
                        content: " "
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: Enums.spacing.xl
                                            + Enums.settingCard.icon_size
                                            + Enums.spacing.xl
                        anchors.right: projectHomepageButton.left
                        anchors.rightMargin: Enums.spacing.xl
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Enums.spacing.none
                        z: 1

                        Label {
                            objectName: "aboutTitleLabel"
                            width: parent.width
                            type: Enums.label.type_body_strong
                            text: qsTr("MCNeteaseToolPE — 网易我的世界打包工具")
                            wrapMode: Text.NoWrap
                            elide: Text.ElideRight
                        }

                        Row {
                            spacing: Enums.spacing.xxs

                            Label {
                                objectName: "aboutVersionPrefix"
                                type: Enums.label.type_body_small
                                text: qsTr("版本 %1 · 基于")
                                      .arg(appUpdater ? appUpdater.currentVersion : "")
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Label {
                                objectName: "prismQmlHomepageLink"
                                type: Enums.label.type_hyperlink
                                text: "PrismQML"
                                url: prismQmlHomepage
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Label {
                                objectName: "aboutDescriptionSuffix"
                                type: Enums.label.type_body_small
                                text: qsTr("引擎构建。")
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }

                    Button {
                        id: projectHomepageButton
                        objectName: "projectHomepageButton"
                        property url destinationUrl: appProjectHomepage

                        anchors.right: parent.right
                        anchors.rightMargin: Enums.spacing.xl
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("项目主页")
                        style: Enums.button.style_hyperlink
                        onClicked: Qt.openUrlExternally(destinationUrl)
                        z: 1
                    }
                }
            }
        }
    }

    Connections {
        target: backend
        function onPython27WorkersChanged() {
            workerSpin.setValue(backend.python27Workers)
        }
    }
}
