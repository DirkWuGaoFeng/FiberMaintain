import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('../views/MainView.vue') },
    { path: '/dashboard', component: () => import('../views/Dashboard.vue') },
    { path: '/chat', component: () => import('../views/Chat.vue') },
    { path: '/admin/knowledge', component: () => import('../views/KnowledgeAdmin.vue') },
    { path: '/observability', component: () => import('../views/ObservabilityDashboard.vue') },
  ]
})
