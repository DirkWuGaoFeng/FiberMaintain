/**
 * 路由配置 — 懒加载 + 布局嵌套
 */
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    children: [
      {
        path: '',
        name: 'chat',
        component: () => import('@/views/chat/ChatView.vue'),
        meta: { title: 'nav.chat', icon: 'ChatDotRound' },
      },
      {
        path: 'workflow',
        name: 'workflow',
        component: () => import('@/views/workflow/WorkflowView.vue'),
        meta: { title: 'nav.workflow', icon: 'Share' },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/knowledge/KnowledgeView.vue'),
        meta: { title: 'nav.knowledge', icon: 'Collection' },
      },
      {
        path: 'monitor',
        name: 'monitor',
        component: () => import('@/views/monitor/MonitorView.vue'),
        meta: { title: 'nav.monitor', icon: 'DataLine' },
      },
      {
        path: 'topology',
        name: 'topology',
        component: () => import('@/views/topology/TopologyView.vue'),
        meta: { title: 'nav.topology', icon: 'Connection' },
      },
      {
        path: 'tools',
        name: 'tools',
        component: () => import('@/views/tools/ToolsView.vue'),
        meta: { title: 'nav.tools', icon: 'SetUp' },
      },
      {
        path: 'memory',
        name: 'memory',
        component: () => import('@/views/memory/MemoryView.vue'),
        meta: { title: 'nav.memory', icon: 'Box' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫：设置页面标题
router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `光纤维护智能 Agent` : '光纤维护智能 Agent'
})

export default router
