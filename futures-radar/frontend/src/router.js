import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Feed from './views/Feed.vue'
import Variety from './views/Variety.vue'
import Digest from './views/Digest.vue'
import Sources from './views/Sources.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/feed', component: Feed },
    { path: '/variety/:code', component: Variety },
    { path: '/digest', component: Digest },
    { path: '/sources', component: Sources },
  ],
})
