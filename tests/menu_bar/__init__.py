"""D9.3 — NotesMenuBarApp 测试套件(C2 阶段 8 tests).

测试覆盖(8 cases):
    T1. test_app_uses_default_stub          默认 ExpenseServiceStub 注入
    T2. test_app_accepts_custom_service      自定义 expense_service 注入
    T3. test_app_invalid_service_raises      非 ExpenseService 抛 TypeError
    T4. test_app_title_format_initial        初始 title 格式
    T5. test_app_menu_items_registered       4 菜单项注册(无 NSApp 拉起)
    T6. test_on_sync_now_success_path        同步成功 + _refresh_title
    T7. test_on_sync_now_failure_notification 同步失败 + rumps.notification
    T8. test_on_open_privacy_subprocess      授权引导 subprocess 调通

设计原则(沿 D4.7.3 严判范本 + D5.6.4 rumps 隔离):
    - monkeypatch rumps.App → FakeApp(避免 NSApp 拉起)
    - monkeypatch subprocess.run → lambda(避免真跑子进程)
    - 直接调 NotesMenuBarApp._on_sync_now / _on_open_privacy(test 私有方法)
    - 不验 rumps 内部 NSStatusBar 行为(平台层)
"""
