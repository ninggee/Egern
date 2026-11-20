# AdUltra：仅替换起点脚本依赖

## 在 Egern 中使用

把现有 AdUltra 模块的订阅地址替换为：

```text
https://raw.githubusercontent.com/ninggee/Egern/main/modules/adultra-qidian-fix.sgmodule
```

Egern 支持直接添加 Surge 模块地址，参见官方 FAQ：
https://egernapp.com/docs/faq#how-to-add-a-module

请停用或移除原 AdUltra 引用，再启用这个副本，不要让两份同时运行。此模块不是能自动覆盖其他模块依赖的叠加补丁；替换的是模块订阅地址。若其他去广告合集也引用了旧的 app2smile 起点脚本，需要另行停用对应旧规则。

## 改动范围

- 上游模块： https://yfamilys.com/module/adultra.sgmodule
- 上游署名和模块内容原样保留，只有一处 `script-path` 更改：
  - 原：`https://raw.githubusercontent.com/app2smile/rules/master/js/qidian.js`
  - 新：`https://raw.githubusercontent.com/ninggee/Egern/main/scripts/qidian.js`
- 另一条同名 `qidian`（ddgksf2013/Scripts）及其他所有脚本地址、匹配规则、MITM 域名均未改动。
- `scripts/qidian.js` 基于 app2smile 原脚本；仅把 ActivityPopup/Data 为空时的整包日志和错误通知，替换为一条跳过日志；有活动配置时仍沿用原来的清理逻辑，其他通知保留。

## 验证和限制

修复 JS 通过 37 项离线模拟断言；模块与上游快照比较仅一行脚本地址不同。未在真实 Egern/起点 App 中验证。

这修复的是缺少可选配置时的错误提醒，不是对未知新版接口的全面适配。此模块是上游的一次快照，不会自动跟随上游更新；需要同步上游时应重新应用这一处 URL 替换，避免直接覆盖丢失修复。原模块及各依赖脚本的署名、权利和适用条款仍归各原作者。
