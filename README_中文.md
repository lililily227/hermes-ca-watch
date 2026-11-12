# 爱马仕加拿大 Neo Garden 23 三色监测

本仓库监测爱马仕加拿大官网**公开**的站点地图、女包分类页面及三个指定商品链接，利用 Bark 向 iPhone 发送提醒。仅限：

| 货号 | 颜色 |
|---|---|
| `H086418CKAC` | 米白＋黑色 |
| `H086418CKAA` | 米白＋深石板灰 |
| `H086418CKAF` | 米白＋冰川蓝＋深灰 |

**注意**：链接出现或页面可打开，不等于商品有货或能下单。尚未证实官网站点地图比商品分类页早更新。程序不下单、不绕过反机器人保护、不访问内部 API。遇到 403、429、验证码或 robots 限制立即停止。

## 手机通知配置

1. iPhone 安装 **Bark - Custom Notifications**，打开 App 复制你的设备 Key（请勿发给别人）。
2. 进入本仓库 **Settings → Secrets and variables → Actions → New repository secret**。
3. Name 填写 `BARK_KEY`，Secret 填写 Bark 私密 Key。
4. 进入 **Actions → Hermes Canada Neo Garden 23 alerts → Run workflow**，先选 `audit` 检查是否能读取允许公开的数据，再选 `test-push` 测试手机提醒，最后选 `monitor` 建立监测基线。
5. 配置好 `BARK_KEY` 后，计划任务每 15 分钟尝试一次；GitHub 定时任务可能延迟或漏执行。第一次正常运行仅记录基线，不会把历史链接误报为新上架。

## 三种提醒

- **站点地图先发现的候选链接**：链接先在站点地图出现且可公开读取，分类页尚未出现。
- **分类页新增链接**：关注的货号首次出现在分类页。
- **已知商品页面恢复可访问**：先前明确不可用的页面重新能打开，但仍需人工核实能否购买。

`config.json` 内 `target_product_codes` 是唯一目标白名单；仅监测这三个颜色。首次对目标商品详情页记录可访问状态，此后默认每小时检查一次。程序保存 `state.json` 防止重复推送。

## 数据来源与限制

官网：https://www.hermes.com/ca/en/ ；规则：https://www.hermes.com/robots.txt 。公开站点地图：https://www.hermes.com/ca/en/sitemap_index.xml 。如果页面没有可解析的公开链接或官网阻止自动访问，**程序不会绕过保护**，此时提醒可能无法正常工作。请先检查 `audit` 日志，不能把本地测试通过等同于官网实时监测有效。

本项目为个人提醒工具，与 Hermès 没有关联。请勿公开 `BARK_KEY`，不要提高请求频率或使用机器人绕过机制。
