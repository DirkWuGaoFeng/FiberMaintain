import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('../views/RealtimeStats.vue') },
    { path: '/trend', component: () => import('../views/TrendAnalysis.vue') },
    { path: '/chat', component: () => import('../views/ChatPanel.vue') },
    { path: '/knowledge', component: () => import('../views/KnowledgeManage.vue') },
  ]
})