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

这修复的是缺少可选配置时的错误提醒，不是对未知新版接口的全面适配。原模块及各依赖脚本的署名、权利和适用条款仍归各原作者。

## 每日自动同步

工作流：`.github/workflows/sync-adultra.yml`，在 GitHub Actions 中显示为 **Sync AdUltra**。

- 每天北京时间 **05:23** 计划运行（cron：`23 21 * * *`，UTC）；GitHub 调度可能延迟，不保证准点。
- 也可以在仓库 **Actions → Sync AdUltra → Run workflow** 手动触发。
- 从原站下载完整 AdUltra，校验六个配置节及目标脚本规则，再且仅再应用一处 URL 替换。
- 上游内容没有变化时不创建提交；有变化时仅提交 `modules/adultra-qidian-fix.sgmodule`。
- 下载失败、Cloudflare 验证页、模块结构变化、目标 URL 消失或重复时，任务失败，保留仓库里最后一次有效的模块，不使用第三方镜像兜底。
- `scripts/qidian.js` 修复版本身不会被自动覆盖；它的更新需要单独审阅。
- 同步在 GitHub 上运行，不依赖手机或 Minis 保持打开；Egern 仍需按自身的更新设置刷新模块。
- 公共仓库长期没有活动时，GitHub 可能自动停用定时工作流；可在 Actions 页面检查并重新启用。

同步脚本仅使用 Python 标准库；可离线验证：

```sh
python3 -m unittest discover -s tests -v
python3 tools/sync_adultra.py --source-file /path/to/original-adultra.sgmodule
```

