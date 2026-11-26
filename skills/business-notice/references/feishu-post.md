# 飞书富文本消息（post）怎么拼

群通知、汇报都用 post：每一行是一个段落，段落里放一个 `md` 标签，飞书按 Markdown 子集渲染（加粗、列表、引用、链接、@）。

```python
import json
rows = []
def md(t): rows.append([{"tag": "md", "text": t}])
def blank(): rows.append([{"tag": "text", "text": ""}])   # 段与段之间的空行

md('📢 **【<项目>｜<主题>】** <at user_id="all"></at>')
md('开场一段：为什么做、给大家带来什么。具体安排如下：')
blank()
md('**一、<范围>｜<一句话要点>**')
md('- **要点：** 说明；\n- **要点：** 说明。')
md('🖼️ 【此处放图：<画面>】')
blank()
md('> “群友原话”<at user_id="ou_xxx"></at>')            # 引用原话并 @ 提出人
json.dump({"zh_cn": {"title": "", "content": rows}}, open("post.json", "w"), ensure_ascii=False)
```

- 发送：`lark-cli im +messages-send --as bot --user-id <open_id> --msg-type post --content "$(cat post.json)"`；读回 `+messages-mget --as bot --message-ids <id>`；改稿 `+messages-edit --as bot --message-id <id> --content ...`。
- 一条消息放不下时按节拆成两条，第二条从下一节标题开始，不重复首行。
- 有序列表写 `1. **短语：** 说明`；节内细分用 `- **要点：** 说明`。
- 汉字和数字、字母紧挨时，飞书会自动加空格；要保持原话不变（如引用群友原话）时，在两者之间插零宽空格 `​`。
- @ 某人用 `<at user_id="ou_..."></at>`，open_id 要和发送用的应用一致（全局坑 G-43）。@所有人用 `user_id="all"`。
- 图片：截图先裁掉或遮住客户姓名、账号、聊天内容，再上传拿 `image_key`；预览阶段只留图位。
