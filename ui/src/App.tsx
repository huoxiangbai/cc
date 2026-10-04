import React from 'react';
import { ConfigProvider } from 'antd';
import { RouterProvider } from 'react-router-dom';
import zhCN from 'antd/locale/zh_CN';
import router from './router';
import AdminLogin from './components/AdminLogin';

// App 组件：应用的根组件，设置全局配置和路由
const App: ReactorType.FC = React.memo(() => {
  return (
    <ConfigProvider locale={zhCN}>
      <RouterProvider router={router} />
      <AdminLogin />
    </ConfigProvider>
  );
});

export default App;
