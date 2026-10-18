# MioVRCA 社区

MioVRCA（VRChat 素材管理与改模工具）的社区数据：玩家分享的**装配方案**、**实测数据**（衣服在各个素体上是否穿模、怎样修好的），以及「社区（实验性）」中的**创作者名片**和**作品**。MioVRCA 直接读取这个仓库，不需要另外下载。

[MioVRCA 官网](https://miovrc.com/vrca/) ・ English / 日本語: see below

## 玩家

- **社区（实验性）**：MioVRCA 的「社区（实验性）」页面。浏览作品和创作者，关注喜欢的创作者（关注只保存在你自己的电脑上）。
  - **创作者名片**：「我的名片」中填写昵称、头像、简介、常用素体、VRChat 主页和其他链接，点「发布到 GitHub」。名片属于你的 GitHub 账号，会自动收录；要修改，编辑后再发布一次即可。生日、关注列表和素材展示柜只在你勾选时才公开。展示柜可从素材库选择最多 60 件带 Booth 商品编号的素材；查看名片时会显示双方共有和自己缺少的素材，并可加入愿望单。
  - **作品**：点「发布作品」填写标题、封面、视频链接（视频放在哔哩哔哩、YouTube 等网站上）、同款素材和链接，可以附上一个装配方案，并选择参考的作品。作品页面的「我也做了」会填入参考作品及其素材列表，发布前可以修改或清除。原作页面显示「做同款的作品」，创作者页统计其他作者参考其作品的次数。作品由维护者查看后发布。在作品的议题上点 👍 就是点赞。
  - **新人作品**：首页显示最近 7 天发布、且作者在 `works.json` 中恰好有一件作品的作品。
- **用社区方案**：MioVRCA 的流水线页 →「装配方案」→「社区方案」，或「社区（实验性）→ 装配方案」。先看所需素材（会标出你的素材库里已经有哪些），再导入。方案只记录素材在工程中的位置和菜单结构，不包含素材文件，素材需要自己购买。
- **分享方案**：「装配方案」里在你的方案上点「分享」→「在 GitHub 上提交」，会打开一个填好的提交页面，登录 GitHub 后点「Create」。
- **分享实测数据**：「设置」→「社区实测数据」→「在 GitHub 上分享」。实测数据只有 Booth 商品编号、衣服和 prefab 的名称、素体名称、穿模的顶点数、用到的形态键名称，不含工程路径和账号信息。

提交到这里的内容都是公开的。方案、实测数据和作品经维护者查看后才会收录。看到有问题的作品或名片，可以在 MioVRCA 中点「举报」。

## 维护者

### 第一次设置

1. 把仓库改名为 `CokoIya/MioVRCA-community`（MioVRCA 按这个名字读取；默认分支为 `main`）。
2. 把这个文件夹里的全部文件上传（包括 `.github` 文件夹和空文件夹中的 `.gitkeep`）。
3. 在仓库的 Issues → Labels 中新建这些标签：`方案`、`实测数据`、`名片`、`作品`、`举报`、`收录`。
4. Settings → Actions → General → Workflow permissions 选「Read and write permissions」（收录时要提交文件、回复议题）。
5. Settings → Secrets and variables → Actions → Variables 中可以新建两个变量（不建时按默认值）：
   - `AUTO_PROFILES`：名片是否自动收录。默认 `true`；设为 `false` 时，名片也要加「收录」标签。
   - `AUTO_WORKS`：没有网盘链接的作品是否自动发布。默认 `false`（作品都由维护者查看后发布）。
6. Settings → General 最下方把仓库改为公开（Change visibility → Public）。私有仓库 MioVRCA 读取不到。

### 收录

玩家提交后会出现一个议题（issue）。

- **方案、实测数据、作品**：看一下内容没问题，就给议题加上 **`收录`** 标签：GitHub Actions 会自动解开分享码、检查、存入仓库、更新列表，然后回复并关闭议题。检查不通过时，会在议题里回复原因，不会改动仓库。作品的封面会被重新绘制为 640×360 的图片。
- **名片**：提交时自动收录（头像重新绘制为 256×256 的图片），名片属于提交议题的 GitHub 账号。
- **删除作品**：作者本人提交「删除作品」时自动删除。
- **举报**：不会自动处理。需要时手动删除对应的文件（见下方），再运行 `python scripts/rebuild.py`。

不收录的议题直接关闭即可。

同一时间只处理一个议题。同时提交的议题较多时，GitHub 可能取消排队中的运行（Actions 页面显示 Cancelled）：名片、作品和删除作品的议题会由每 6 小时一次的定时任务补上处理；方案和实测数据请把「收录」标签去掉再加一次。

定时任务和每次重建作品列表都会统计点赞数（作品议题上的 👍，每 100 个议题一次请求）。在 Actions 页面选「收录」→「Run workflow」可以立即运行一次。

### 删改

- 删除一个方案：删掉 `recipes/` 中对应的文件，然后运行 `python scripts/rebuild.py`（列表里没有文件的方案会被去掉），提交。
- 改方案名称、说明：直接编辑 `index.json` 中对应的条目，提交。
- 删除某次提交的实测数据：删掉 `fits/` 中对应的文件，运行 `python scripts/rebuild.py`，提交。
- 删除一个作品：删掉 `works/w<号>.json` 和 `covers/w<号>.jpg`，运行 `python scripts/rebuild.py`，提交。
- 删除一张名片：删掉 `profiles/<用户名>.json` 和 `avatars/<用户名>.jpg`，运行 `python scripts/rebuild.py`，提交。
- 不允许使用的词语：写在 `scripts/banned.txt` 中（每行一个），含有它们的提交会被拒绝。

手动运行 `python scripts/rebuild.py` 时，默认从 `CokoIya/MioVRCA-community` 读取点赞数。仓库名不同时设置环境变量 `GITHUB_REPOSITORY`；可设置 `GITHUB_TOKEN` 使用有读取权限的令牌。网络读取失败时不会推送更改，应恢复连接后重试。

MioVRCA 每隔一段时间读取一次（GitHub 的原始文件，读不到时用 jsDelivr 的镜像，镜像最多可能晚 12 小时）。

## 文件

| 文件 | 内容 |
|---|---|
| `index.json` | 方案列表：编号、名称、说明、素体、署名、提交者、链接、所需素材、文件的校验值；以及 `fits.json` 的校验值 |
| `recipes/<编号>.json` | 方案文件（和 MioVRCA「导出为文件」的格式相同） |
| `fits/issue-<号>.json` | 每次提交的实测数据 |
| `fits.json` | 实测数据汇总：每件衣服（商品编号 + prefab）在每个素体上的实测人数、最终没有穿模的人数、一穿上就没有穿模的人数、各形态键被设置的人数 |
| `profiles/<用户名>.json` | 创作者名片；可选 `showcase` 素材展示柜，最多 60 件，每件含 `booth_id`、`name` 和可选 `shop`，不允许重复的商品编号 |
| `avatars/<用户名>.jpg` | 名片的头像（没有时显示 GitHub 头像） |
| `creators.json` | 创作者列表：昵称、头像、常用素体、语言、公开的生日、关注人数（只算公开了关注列表的名片）、作品数、方案数 |
| `works/w<号>.json` | 作品：标题、说明、视频链接、素体、同款素材、链接、附带的方案分享码；可选 `based_on` 指向参考作品（如 `w12`），不能指向自身 |
| `covers/w<号>.jpg` | 作品的封面 |
| `works.json` | 作品列表，最新的在前，保留 `based_on` 参考关系 |
| `likes.json` | 每个作品的点赞数（定时任务统计） |
| `scripts/` | 收录和整理用的脚本（只用 Python 标准库；重新绘制图片时用 Pillow） |
| `tests/` | 脚本的测试：`python -m unittest discover tests` |

同一位玩家对同一件衣服、同一个素体的多次实测数据，只算最新的一次。MioVRCA 在至少 3 位玩家、且至少一半的玩家这样设置时，才会自动套用某个形态键。

## 许可证

脚本以 GPL-3.0 或 PolyForm Noncommercial 1.0.0 授权（和 MioVRCA 一样，任选其一）；玩家提交的方案、实测数据、名片和作品以 CC BY-NC-SA 4.0 公开。提交即表示同意按这个方式公开，并允许 MioVRCA 使用。详见 [LICENSE.md](LICENSE.md)。

---

## English

Community data for MioVRCA (a VRChat asset manager): **presets** and **fit data** shared by players, and the **creator cards** and **works** of the app's Community (experimental) page. MioVRCA reads this repository directly. Creator cards belong to the GitHub account that submits them and are accepted automatically; works, presets and fit data are reviewed by a maintainer, who adds the `收录` label to publish them. A 👍 on a work's issue is a like. Everything here is public. Scripts: GPL-3.0 or PolyForm Noncommercial 1.0.0 (your choice); submitted content: CC BY-NC-SA 4.0. See [LICENSE.md](LICENSE.md).

## 日本語

MioVRCA（VRChat アセット管理ツール）のコミュニティデータです。プレイヤーが共有した**プリセット**と**実測データ**、そして「コミュニティ（試験運用）」の**クリエイターカード**と**作品**を置いています。MioVRCA が直接読み込みます。クリエイターカードは投稿した GitHub アカウントのもので、自動で反映されます。作品・プリセット・実測データは管理者が確認し、`收录` ラベルを付けると公開されます。作品の Issue に付いた 👍 が「いいね」です。ここにあるものはすべて公開されます。スクリプトは GPL-3.0 または PolyForm Noncommercial 1.0.0（選択可）、投稿された内容は CC BY-NC-SA 4.0 です。詳しくは [LICENSE.md](LICENSE.md) をご覧ください。
