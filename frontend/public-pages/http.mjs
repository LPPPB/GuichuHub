import {resolvePublicPath} from '../src/routing/publicRoutes.js'

export function createPublicPageHandler({publisher,buildId}) {
  return (request,response)=>{
    const send=(status,body='',headers={})=>{
      response.writeHead(status,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-cache',...headers})
      response.end(request.method==='HEAD'?'':body)
    }
    if(!['GET','HEAD'].includes(request.method))return send(405,'Method not allowed',{Allow:'GET, HEAD'})
    // Parse origin-form without URL normalization hiding encoded/duplicate paths.
    const raw=request.url || '/'
    const index=raw.indexOf('?'),path=index<0?raw:raw.slice(0,index),query=index<0?'':raw.slice(index)
    if(path==='/health/live')return send(200,'ok',{'Content-Type':'text/plain; charset=utf-8'})
    if(path==='/__public-pages/build')return send(200,buildId,{'Content-Type':'text/plain; charset=utf-8'})
    const resolved=resolvePublicPath(path)
    if(resolved.kind==='redirect')return send(308,'',{Location:resolved.location+query})
    if(resolved.kind!=='page')return send(404,'<h1>页面不存在</h1>',{'X-Robots-Tag':'noindex'})
    const page=publisher.snapshot().get(path)
    if(!page)return send(503,'<h1>公开数据暂不可用</h1>',{'Retry-After':'60','X-Robots-Tag':'noindex'})
    const conditions=(request.headers['if-none-match'] || '').split(',').map(v=>v.trim().replace(/^W\//,''))
    if(conditions.includes('*') || conditions.includes(page.etag))return send(304,'',{ETag:page.etag})
    return send(200,page.html,{ETag:page.etag})
  }
}
