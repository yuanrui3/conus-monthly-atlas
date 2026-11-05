// Shareable links to existing atlas views; ordinary HTML section anchors are unaffected.
const views=new Map([['#river-flow','water'],['#overview','map'],['#local-detail','detail']]);
function followAtlasLink(){const view=views.get(location.hash);if(view)window.NovemberAtlas?.openView(view);}
window.addEventListener('hashchange',followAtlasLink);
window.addEventListener('DOMContentLoaded',followAtlasLink,{once:true});
document.addEventListener('click',e=>{const a=e.target.closest('a[href="#river-flow"]');if(a&&location.hash==='#river-flow')followAtlasLink();});

document.addEventListener('atlas:view',e=>{const u=new URL(location.href);if(e.detail?.view==='water'){if(u.hash!=='#river-flow'){u.hash='river-flow';history.replaceState(null,'',u);}}else if(u.hash==='#river-flow'){u.hash='';history.replaceState(null,'',u);}});
