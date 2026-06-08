"""LLM Prompt 模板集合 — D4.6 起步.

每个 prompt 是一个常量字符串,直接喂给 `router.route(TaskType.X, messages)`.

设计原则:
  - 中文为主 (项目主场景是国内邮件)
  - system 提示 + user 输入分离 (OpenAI 风格)
  - 严禁把可变对象 (如 dict / list) 暴露为 prompt 内部状态
  - 每个 prompt 配 "任务元数据" 段,便于 trace 关联(后续可加 fingerprint)
"""
