import { useEffect, useState } from 'react';
import { Form, Input, Modal } from 'antd';
import request from '@/utils/request';

/** Entry for the approved server-side admin session; credentials stay in this form. */
export default function AdminLogin() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener('reactor-admin-login-required', show);
    return () => window.removeEventListener('reactor-admin-login-required', show);
  }, []);
  const submit = async () => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      await request.post('/api/v1/admin/admin-user/login', values);
      form.resetFields();
      setOpen(false);
      // Existing configuration pages query their state on mount.
      window.location.reload();
    } finally { setBusy(false); }
  };
  return <Modal title="管理员登录" open={open} confirmLoading={busy} okText="登录" cancelText="取消"
    onOk={() => void submit().catch(() => undefined)} onCancel={() => { form.resetFields(); setOpen(false); }}>
    <Form form={form} layout="vertical" onFinish={() => void submit().catch(() => undefined)}>
      <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
        <Input autoComplete="username" />
      </Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
        <Input.Password autoComplete="current-password" onPressEnter={() => void submit().catch(() => undefined)} />
      </Form.Item>
    </Form>
  </Modal>;
}
