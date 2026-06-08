"""D4.4 — 任务策略板 (Task Policy Board) 测试包.

覆盖:
  - exceptions: 5 业务异常 + PolicyError 基类层级
  - task_packet: 8 必含字段契约 + JSON 双向 + 向后兼容 + Builder
  - heartbeat: 3 状态 + update/evaluate + assert_alive
  - lane_board: 3 lanes + 状态转换 + freshness + status JSON
  - policy_engine: 6 决策 + EventStore 集成

参考: claw-code `g006-task-policy-board-verification-map.md`
"""
