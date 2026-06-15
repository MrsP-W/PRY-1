"""D9.4 — note_structurer prompts 测试占位.

测试覆盖(8 cases):
  T1. test_six_prompts_distinct       6 个 SYSTEM prompt 各不相同(关键词差异)
  T2. test_all_prompts_non_empty      6 个 prompt 都非空
  T3. test_all_prompts_contain_bare_json_contract  契约 2 关键词(严格 JSON / 无 markdown)
  T4. test_build_system_prompt_dispatch  6 类分发 + None 走 DEFAULT
  T5. test_build_system_prompt_reject  非法 note_category 抛 ValueError
  T6. test_build_user_message_basic   3 字段 + UNTRUSTED_DATA 块 + 抗注入
  T7. test_build_user_message_truncates_body  body 截断到 2000 字符
  T8. test_build_user_message_rejects_invalid  type 错 / 非法 note_category

设计: 沿 tests/ai/test_draft_prompts.py 范本(2 个文件覆盖 prompts 单元测试,
不重复覆盖业务层 test_structurer.py)。
"""
