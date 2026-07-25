// SPDX-License-Identifier: GPL-3.0-or-later
// 设置页面
// 自动更新入口:只提供宿主配置并调用引擎门面，状态反馈与完整流程由 PrismQML 编排。
import QtQuick
import PrismQML

Item {
    id: page

    // AsyncQmlPage 为所有页面统一传入的占位属性 / placeholder accepted by AsyncQmlPage
    property var backend: null

    function iconPath(name) {
        return Enums.iconPath + name + ".svg"
    }

    Component {
        id: updateFeedbackPresenter

        AutoUpdaterProgressDialogPresenter {}
    }

    AutoUpdater {
        id: autoUpdater
        updater: appUpdater
        silentArgs: appInstallerSilentArgs
        notifyWhenUpToDate: true
        feedbackPresenter: updateFeedbackPresenter
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
                    text: qsTr("审核性能、自动更新与应用信息。")
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
