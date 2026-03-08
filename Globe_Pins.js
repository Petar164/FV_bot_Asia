"use client";import{jsx as _jsx,jsxs as _jsxs}from"react/jsx-runtime";import{useEffect,useRef,useState}from"react";import{addPropertyControls,ControlType,RenderTarget}from"framer";const URL_THREE="https://esm.sh/three@0.157?bundle";const URL_ORBIT="https://esm.sh/three@0.157/examples/jsm/controls/OrbitControls?bundle";const URL_TOPO="https://esm.sh/topojson-client@3?bundle";// Postprocessing (Three examples)
const URL_EFFECT_COMPOSER="https://esm.sh/three@0.157/examples/jsm/postprocessing/EffectComposer?bundle";const URL_RENDER_PASS="https://esm.sh/three@0.157/examples/jsm/postprocessing/RenderPass?bundle";const URL_UNREAL_BLOOM_PASS="https://esm.sh/three@0.157/examples/jsm/postprocessing/UnrealBloomPass?bundle";const URL_SHADER_PASS="https://esm.sh/three@0.157/examples/jsm/postprocessing/ShaderPass?bundle";const URL_FILM_PASS="https://esm.sh/three@0.157/examples/jsm/postprocessing/FilmPass?bundle";const URL_OUTPUT_PASS="https://esm.sh/three@0.157/examples/jsm/postprocessing/OutputPass?bundle";const URL_RGB_SHIFT_SHADER="https://esm.sh/three@0.157/examples/jsm/shaders/RGBShiftShader?bundle";let THREE;const MAX_DPR=2;const FPS_CAP=50;const MAX_FILL_POINTS=12e4;const DEFAULT_PROPS={autoRotateSpeed:.03,pointSize:.006,tileDeg:1,zoom:false,pins:[{lon:-118.2437,lat:34.0522,name:"USA",address:"Los Angeles, Beverly Hills 55a",phone:"+1 213-555-0173"},{lon:-.1278,lat:51.5074,name:"United Kingdom",address:"London, Borton str. 88",phone:"+44 20 7946 0958"},{lon:139.6917,lat:35.6895,name:"Japan",address:"Tokyo, Shibuya 109",phone:"+81 3-3477-5111"}],pointColor:"#7AE1FF",labelColor:"#E7F8FF",pinDotColor:"#7AE1FF",pinPanelBgColor:"#0C2A33",pinPanelBgOpacity:.75,pinPanelBorderColor:"#7AE1FF",backOpacity:.3,fillColor:"#7AE1FF",fillOpacity:.6,showLabels:true,pinSize:.012,haloScale:10,labelFont:{family:"Inter",style:"Regular"},labelFontSize:12,preloaderTheme:"Dark",initialRotationY:0,stopMotionInEditor:true,showTrails:true,trailColor:"#40C5E3",enableBloom:false,enableChromaticAberration:false,enableFilm:false,enableGlitch:false,fxIntensity:.6};const layerCache=new Map;let DOT_TEX,HALO_TEX;let LAND_POLYS=null;let LAND_GEO_POLYS=null;function Preloader({progress,theme="Dark"}){const isLight=theme==="Light";const color=isLight?"#fff":"#000";const ringBg=isLight?"rgba(255,255,255,.35)":"rgba(0,0,0,.2)";return /*#__PURE__*/_jsxs("div",{style:{position:"absolute",inset:0,display:"flex",alignItems:"center",justifyContent:"center",background:"rgba(0,0,0,0)",color,zIndex:10,fontSize:10,pointerEvents:"none"},children:[/*#__PURE__*/_jsxs("div",{children:[/*#__PURE__*/_jsx("div",{style:{width:36,height:36,borderRadius:"50%",border:`3px solid ${ringBg}`,borderTopColor:color,animation:"spin .8s linear infinite"}}),/*#__PURE__*/_jsxs("div",{style:{marginTop:8,textAlign:"center"},children:[Math.round(progress),"%"]})]}),/*#__PURE__*/_jsx("style",{children:`@keyframes spin{to{transform:rotate(360deg)}}`})]});}// Safe check for Framer editor
function isEditorCanvas(){try{return RenderTarget.current()===RenderTarget.canvas;}catch{return false;}}/**
 * @framerSupportedLayoutWidth any-prefer-fixed
 * @framerSupportedLayoutHeight any-prefer-fixed
 * @framerIntrinsicWidth 600
 * @framerIntrinsicHeight 600
 */// ================= Component =================
export default function Globe_Pins(props){const cfg={...DEFAULT_PROPS,...props};const containerRef=useRef(null);const rafRef=useRef(0);const runningRef=useRef(false);const[loading,setLoading]=useState(true);const[progress,setProgress]=useState(0);useEffect(()=>{let disposed=false;let cleanup;const run=async()=>{const safeSetLoading=v=>{if(!disposed)setLoading(v);};const safeSetProgress=v=>{if(!disposed)setProgress(v);};safeSetLoading(true);safeSetProgress(0);// Capture DOM reference initially
const container=containerRef.current;if(!container)return;// Clear previous children carefully
while(container.firstChild){container.removeChild(container.firstChild);}const getDims=()=>{const w=container.clientWidth||800;const h=container.clientHeight||800;return{width:w,height:h};};safeSetProgress(10);// --- ASYNC IMPORTS START ---
if(!THREE)THREE=await import(/* @vite-ignore */URL_THREE);if(disposed)return;const{OrbitControls}=await import(/* @vite-ignore */URL_ORBIT);if(disposed)return;safeSetProgress(20);// --- INITIALIZE THREE.JS ---
const{width,height}=getDims();const scene=new THREE.Scene;const camera=new THREE.PerspectiveCamera(55,width/height,.1,100);camera.position.set(0,0,3);const renderer=new THREE.WebGLRenderer({antialias:false,alpha:true,powerPreference:"low-power",premultipliedAlpha:true});renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,MAX_DPR));renderer.setSize(width,height);renderer.setClearColor(0,0);// SAFETY CHECK: If component unmounted during async await, STOP.
if(disposed||!containerRef.current){renderer.dispose();return;}container.appendChild(renderer.domElement);const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.enablePan=false;controls.enableZoom=!!cfg.zoom;let roContainer=null;// ---- Post FX Variables ----
let composer=null;let bloomPass=null;let rgbShiftPass=null;let filmPass=null;let glitchPass=null;let onControlsChange=null;const globeGroup=new THREE.Group;globeGroup.rotation.y=cfg.initialRotationY*(Math.PI/180);scene.add(globeGroup);if(!DOT_TEX)DOT_TEX=makeCircleDotTexture(64);if(!HALO_TEX)HALO_TEX=makeHaloTexture();// Pins
const pinGroups=[];const pinSpheres=[];const pinPositions=[];cfg.pins.forEach(p=>{const{g,pos}=addPin(globeGroup,p,HALO_TEX,null,cfg.labelColor,cfg.pinDotColor,cfg.pinPanelBgColor,cfg.pinPanelBgOpacity,cfg.pinPanelBorderColor,cfg.labelFont,cfg.labelFontSize,cfg.pinSize,cfg.haloScale);pinGroups.push(g);pinSpheres.push(g.children[0]);pinPositions.push(pos);});safeSetProgress(35);// --- FETCH LAND DATA ---
let{polys,geoPolys}=await getLand().catch(()=>({polys:null,geoPolys:null}));// Re-check disposed
if(disposed){renderer.dispose();if(renderer.domElement.parentElement)renderer.domElement.parentElement.removeChild(renderer.domElement);return;}if(!polys||!polys.length||!geoPolys){// Fallback or error handling
safeSetLoading(false);return;}const filtered=filterNonPolarPolys(polys,geoPolys);polys=filtered.polys;geoPolys=filtered.geoPolys;const edgeMat=makePointsMat(cfg.pointColor,cfg.pointSize,cfg.backOpacity,DOT_TEX);const fillMat=makePointsMat(cfg.fillColor,Math.max(.75*cfg.pointSize,.003),cfg.backOpacity,DOT_TEX,cfg.fillOpacity);let edgePos,fillPos;const cacheKey=cfg.tileDeg;const cached=layerCache.get(cacheKey);if(cached){edgePos=cached.edge;fillPos=cached.fill;safeSetProgress(65);}else{try{safeSetProgress(40);const edge=await buildEdgesInWorker(polys,Math.max(.2,cfg.tileDeg));if(disposed){renderer.dispose();return;}safeSetProgress(70);const fill=await buildFillTileInWorker(geoPolys,cfg.tileDeg);if(disposed){renderer.dispose();return;}edgePos=edge;fillPos=limitPoints(fill,MAX_FILL_POINTS);layerCache.set(cacheKey,{edge:edgePos,fill:fillPos});safeSetProgress(100);}catch{const{edge}=buildEdgesSync(polys,Math.max(.2,cfg.tileDeg));edgePos=edge;fillPos=new Float32Array(0);safeSetProgress(100);}}const edgeGeo=new THREE.BufferGeometry;edgeGeo.setAttribute("position",new THREE.Float32BufferAttribute(edgePos,3));const edgePts=new THREE.Points(edgeGeo,edgeMat);globeGroup.add(edgePts);const fillGeo=new THREE.BufferGeometry;fillGeo.setAttribute("position",new THREE.Float32BufferAttribute(fillPos,3));const fillPts=new THREE.Points(fillGeo,fillMat);globeGroup.add(fillPts);// ---- TRAILS SYSTEM ----
const activeTrails=[];const trailsGroup=new THREE.Group;globeGroup.add(trailsGroup);let trailSpawnTimer=0;const TrailShader={uniforms:{uColor:{value:new THREE.Color(cfg.trailColor)},uProgress:{value:0}},vertexShader:`
                    varying vec2 vUv;
                    void main() {
                        vUv = uv;
                        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                    }
                `,fragmentShader:`
                    uniform vec3 uColor;
                    uniform float uProgress;
                    varying vec2 vUv;
                    void main() {
                        float t = uProgress;
                        float len = 0.35; 
                        float dist = t - vUv.x;
                        if (dist < 0.0 || dist > len) discard;
                        float alpha = 1.0 - (dist / len);
                        alpha = pow(alpha, 2.5);
                        gl_FragColor = vec4(uColor, alpha);
                    }
                `};const spawnTrail=()=>{if(pinPositions.length<2)return;const i1=Math.floor(Math.random()*pinPositions.length);let i2=Math.floor(Math.random()*pinPositions.length);while(i1===i2){i2=Math.floor(Math.random()*pinPositions.length);}const vStart=pinPositions[i1];const vEnd=pinPositions[i2];const dist=vStart.distanceTo(vEnd);const mid=vStart.clone().add(vEnd).multiplyScalar(.5).normalize();const curveHeight=1+dist*.5;const vControl=mid.multiplyScalar(curveHeight);const curve=new THREE.QuadraticBezierCurve3(vStart,vControl,vEnd);const tubeGeo=new THREE.TubeGeometry(curve,24,.003,6,false);const mat=new THREE.ShaderMaterial({uniforms:THREE.UniformsUtils.clone(TrailShader.uniforms),vertexShader:TrailShader.vertexShader,fragmentShader:TrailShader.fragmentShader,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide});mat.uniforms.uColor.value.set(cfg.trailColor);const mesh=new THREE.Mesh(tubeGeo,mat);trailsGroup.add(mesh);activeTrails.push({mesh,progress:0,speed:.3+Math.random()*.4});};// ---- POST FX ----
const fxEnabled=cfg.enableBloom||cfg.enableChromaticAberration||cfg.enableFilm||cfg.enableGlitch;const clamp01=v=>Math.max(0,Math.min(1,v));const fx=clamp01(cfg.fxIntensity);const GlitchShader={uniforms:{tDiffuse:{value:null},uTime:{value:0},uAmount:{value:0},uSeed:{value:0}},vertexShader:`
                    varying vec2 vUv;
                    void main() {
                        vUv = uv;
                        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                    }
                `,fragmentShader:`
                    uniform sampler2D tDiffuse;
                    uniform float uTime;
                    uniform float uAmount;
                    uniform float uSeed;
                    varying vec2 vUv;
                    float hash(float n) { return fract(sin(n) * 43758.5453123); }
                    float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
                    void main() {
                        vec2 uv = vUv;
                        float t = uTime + uSeed * 10.0;
                        float gate = smoothstep(0.92, 1.0, sin(t * 1.7) * 0.5 + 0.5);
                        gate *= smoothstep(0.88, 1.0, sin(t * 2.9) * 0.5 + 0.5);
                        float amt = uAmount * gate;
                        float band = step(0.985, hash2(vec2(floor(uv.y * 140.0), floor(t * 18.0))));
                        float offset = (hash(uv.y * 1000.0 + t * 20.0) - 0.5) * 2.0;
                        uv.x += offset * amt * (0.4 + 0.6 * band);
                        vec2 rUv = uv + vec2(amt * 0.15, 0.0);
                        vec2 bUv = uv - vec2(amt * 0.15, 0.0);
                        vec4 base = texture2D(tDiffuse, uv);
                        vec4 split;
                        split.r = texture2D(tDiffuse, rUv).r;
                        split.g = base.g;
                        split.b = texture2D(tDiffuse, bUv).b;
                        split.a = base.a;
                        vec4 col = mix(base, split, amt);
                        float line = step(0.992, hash2(vec2(floor(t * 32.0), floor(uv.y * 220.0))));
                        col.rgb = mix(col.rgb, col.rgb * 0.6, line * amt * 8.0);
                        gl_FragColor = col;
                    }
                `};if(fxEnabled){const[composerMod,renderPassMod,bloomMod,shaderPassMod,filmMod,rgbShaderMod,outputMod]=await Promise.all([import(/* @vite-ignore */URL_EFFECT_COMPOSER),import(/* @vite-ignore */URL_RENDER_PASS),import(/* @vite-ignore */URL_UNREAL_BLOOM_PASS),import(/* @vite-ignore */URL_SHADER_PASS),import(/* @vite-ignore */URL_FILM_PASS),import(/* @vite-ignore */URL_RGB_SHIFT_SHADER),(async()=>{try{return await import(/* @vite-ignore */URL_OUTPUT_PASS);}catch{return null;}})()]);if(disposed){renderer.dispose();return;}const EffectComposer=composerMod.EffectComposer;const RenderPass=renderPassMod.RenderPass;const UnrealBloomPass=bloomMod.UnrealBloomPass;const ShaderPass=shaderPassMod.ShaderPass;const FilmPass=filmMod.FilmPass;const RGBShiftShader=rgbShaderMod.RGBShiftShader;const OutputPass=outputMod?.OutputPass;composer=new EffectComposer(renderer);composer.setPixelRatio(renderer.getPixelRatio());composer.setSize(width,height);composer.addPass(new RenderPass(scene,camera));if(cfg.enableBloom){const strength=.15+1.15*fx;const radius=.01+.15*fx;const threshold=.1;bloomPass=new UnrealBloomPass(new THREE.Vector2(width,height),strength,radius,threshold);composer.addPass(bloomPass);}if(cfg.enableChromaticAberration&&RGBShiftShader){rgbShiftPass=new ShaderPass(RGBShiftShader);if(rgbShiftPass?.uniforms?.amount)rgbShiftPass.uniforms.amount.value=5e-4+.0065*fx;if(rgbShiftPass?.uniforms?.angle)rgbShiftPass.uniforms.angle.value=0;composer.addPass(rgbShiftPass);}if(cfg.enableFilm){filmPass=new FilmPass(.08*fx,.25*fx,512,false);composer.addPass(filmPass);}if(cfg.enableGlitch){glitchPass=new ShaderPass(GlitchShader);glitchPass.uniforms.uAmount.value=.001+.02*fx;composer.addPass(glitchPass);}if(OutputPass){composer.addPass(new OutputPass);}else{const passes=composer.passes||[];for(let i=0;i<passes.length;i++)passes[i].renderToScreen=false;if(passes.length)passes[passes.length-1].renderToScreen=true;}}// ===== LABELS =====
const css2d=await import(/* @vite-ignore */"https://esm.sh/three@0.157/examples/jsm/renderers/CSS2DRenderer?bundle");if(disposed){renderer.dispose();return;}const{CSS2DRenderer,CSS2DObject}=css2d;function getHostDoc(){try{// Try to use the same document where the component is
if(containerRef.current&&containerRef.current.ownerDocument){return containerRef.current.ownerDocument;}if(window.top&&window.top.document&&window.top.document.body)return window.top.document;}catch{}return document;}const HOST_DOC=getHostDoc();const overlayHost=HOST_DOC.createElement("div");Object.assign(overlayHost.style,{position:"fixed",inset:"0",pointerEvents:"none",zIndex:"1000",overflow:"visible"});HOST_DOC.body.appendChild(overlayHost);const overlayAnchor=HOST_DOC.createElement("div");Object.assign(overlayAnchor.style,{position:"absolute",left:"0px",top:"0px",width:"0px",height:"0px",overflow:"visible"});overlayHost.appendChild(overlayAnchor);const labelRenderer=new CSS2DRenderer;overlayAnchor.appendChild(labelRenderer.domElement);Object.assign(labelRenderer.domElement.style,{position:"absolute",left:"0",top:"0",pointerEvents:"none",background:"transparent"});const syncOverlay=()=>{if(!renderer||!renderer.domElement)return;const rect=renderer.domElement.getBoundingClientRect();// If rect is zero (hidden/initializing), skip
if(rect.width===0&&rect.height===0)return;let left=rect.left,top=rect.top;// Correction for frames if cross-origin allows
if(HOST_DOC!==document){try{const frameEl=window.frameElement;if(frameEl){const fRect=frameEl.getBoundingClientRect();left+=fRect.left;top+=fRect.top;}}catch{}}overlayAnchor.style.left=`${left}px`;overlayAnchor.style.top=`${top}px`;overlayAnchor.style.width=`${rect.width}px`;overlayAnchor.style.height=`${rect.height}px`;labelRenderer.setSize(rect.width,rect.height);const hostWin=HOST_DOC.defaultView||window;const rectLeft=left,rectTop=top;const rectRight=left+rect.width,rectBottom=top+rect.height;const vw=hostWin.innerWidth,vh=hostWin.innerHeight;const inView=rectRight>0&&rectBottom>0&&rectLeft<vw&&rectTop<vh;labelRenderer.domElement.style.display=inView?"block":"none";if(inView&&cfg.stopMotionInEditor&&isEditorCanvas()){requestAnimationFrame(()=>renderOnce(0));}};let lastRect={l:0,t:0,w:0,h:0};if(cfg.stopMotionInEditor&&isEditorCanvas()){const watchRect=()=>{if(disposed)return;const r=renderer.domElement.getBoundingClientRect();if(r.left!==lastRect.l||r.top!==lastRect.t||r.width!==lastRect.w||r.height!==lastRect.h){lastRect={l:r.left,t:r.top,w:r.width,h:r.height};syncOverlay();}requestAnimationFrame(watchRect);};watchRect();}syncOverlay();// Observers for sync
let roLocal=null;let roHost=null;try{roLocal=new ResizeObserver(syncOverlay);roLocal.observe(document.documentElement);}catch{}try{if(HOST_DOC!==document){roHost=new ResizeObserver(syncOverlay);roHost.observe(HOST_DOC.documentElement);}}catch{}const onResize=()=>syncOverlay();const onScroll=()=>syncOverlay();window.addEventListener("resize",onResize,{passive:true});window.addEventListener("scroll",onScroll,{passive:true});HOST_DOC.addEventListener("scroll",onScroll,{capture:true,passive:true});// Add DOM Labels
const hasLabels=cfg.pins.some(p=>p.name||p.address||p.phone);if(hasLabels){pinGroups.forEach(g=>{const pin=g.__pin;if(!(pin.name||pin.address||pin.phone))return;const el=HOST_DOC.createElement("div");const bg=hexToRgba(cfg.pinPanelBgColor,cfg.pinPanelBgOpacity);const ff=fontFamilyFromControl(cfg.labelFont);el.style.cssText=`max-width:280px;`+`white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-break:anywhere;hyphens:auto;`+`padding:12px;border-radius:8px;background:${bg};backdrop-filter:blur(6px);`+`border:1px solid ${cfg.pinPanelBorderColor};color:${cfg.labelColor};`+`pointer-events:none;font-family:${ff};font-size:${cfg.labelFontSize}px;line-height:1.35;`;const nl2br=s=>s.replace(/\n/g,"<br/>");const nameHTML=pin.name?`<b>${pin.name}</b><br/>`:"";const addrHTML=pin.address?`${nl2br(pin.address)}<br/>`:"";const phoneHTML=pin.phone??"";el.innerHTML=`${nameHTML}${addrHTML}${phoneHTML}`;const labelObj=new CSS2DObject(el);labelObj.position.set(0,.08,0);labelObj.visible=!!cfg.showLabels;g.__labelObj=labelObj;g.add(labelObj);});}// Interaction
const raycaster=new THREE.Raycaster;const mouse=new THREE.Vector2;function setMouseNDC(ev){const rect=renderer.domElement.getBoundingClientRect();if(rect.width===0||rect.height===0)return;mouse.x=(ev.clientX-rect.left)/rect.width*2-1;mouse.y=-((ev.clientY-rect.top)/rect.height)*2+1;}function hideAllLabels(){pinGroups.forEach(g=>{const l=g.__labelObj;if(l)l.visible=false;});}const onClick=ev=>{if(!hasLabels||cfg.showLabels)return;setMouseNDC(ev);raycaster.setFromCamera(mouse,camera);const hits=raycaster.intersectObjects(pinSpheres,true);if(hits.length){const group=hits[0].object.parent;const label=group?.__labelObj;if(label){hideAllLabels();label.visible=true;}}else{hideAllLabels();}if(cfg.stopMotionInEditor&&isEditorCanvas())renderOnce(0);};renderer.domElement.addEventListener("click",onClick);// Cursor
let isDragging=false;let isHoveringPin=false;const applyCursor=()=>{renderer.domElement.style.cursor=isHoveringPin?"pointer":isDragging?"grabbing":"grab";};const onDragStart=()=>{isDragging=true;applyCursor();};const onDragEnd=()=>{isDragging=false;applyCursor();};controls.addEventListener("start",onDragStart);controls.addEventListener("end",onDragEnd);const onDown=()=>{isDragging=true;applyCursor();};const onUp=()=>{isDragging=false;applyCursor();};const onLeave=()=>{isDragging=false;applyCursor();};renderer.domElement.addEventListener("mousedown",onDown);renderer.domElement.addEventListener("mouseup",onUp);renderer.domElement.addEventListener("mouseleave",onLeave);renderer.domElement.addEventListener("touchstart",onDown,{passive:true});renderer.domElement.addEventListener("touchend",onUp,{passive:true});function onMouseMove(ev){const rect=renderer.domElement.getBoundingClientRect();if(rect.width===0||rect.height===0)return;mouse.x=(ev.clientX-rect.left)/rect.width*2-1;mouse.y=-((ev.clientY-rect.top)/rect.height)*2+1;raycaster.setFromCamera(mouse,camera);const hits=raycaster.intersectObjects(pinSpheres,true);isHoveringPin=hits.length>0;applyCursor();}renderer.domElement.addEventListener("mousemove",onMouseMove);applyCursor();safeSetLoading(false);// Loop
const clock=new THREE.Clock;const FRAME=1/FPS_CAP;let acc=FRAME;const renderOnce=(delta=0)=>{if(disposed)return;[edgePts.material,fillPts.material].forEach(mat=>{const shader=mat?.userData?.shader;if(shader){shader.uniforms.uCamPos.value.copy(camera.position);shader.uniforms.uBackOpacity.value=cfg.backOpacity;}});// Trails
if(cfg.showTrails){trailSpawnTimer+=delta;if(trailSpawnTimer>.6&&activeTrails.length<6&&Math.random()>.5){spawnTrail();trailSpawnTimer=0;}for(let i=activeTrails.length-1;i>=0;i--){const trail=activeTrails[i];trail.progress+=trail.speed*delta;if(trail.progress>=1.4){trailsGroup.remove(trail.mesh);trail.mesh.geometry.dispose();trail.mesh.material.dispose();activeTrails.splice(i,1);}else{trail.mesh.material.uniforms.uProgress.value=trail.progress;}}}controls.update();if(glitchPass?.uniforms?.uTime){glitchPass.uniforms.uTime.value+=delta;glitchPass.uniforms.uSeed.value=(glitchPass.uniforms.uSeed.value+delta*.13)%1e3;}if(composer)composer.render(delta);else renderer.render(scene,camera);labelRenderer.render(scene,camera);};const editorStop=cfg.stopMotionInEditor&&isEditorCanvas();if(editorStop){onControlsChange=()=>renderOnce(0);controls.addEventListener("change",onControlsChange);}const loop=()=>{if(disposed||!runningRef.current)return;const dt=clock.getDelta();acc+=dt;if(cfg.autoRotateSpeed>0)globeGroup.rotation.y+=cfg.autoRotateSpeed*dt;if(!document.hidden&&acc>=FRAME){renderOnce(dt);acc=0;}rafRef.current=requestAnimationFrame(loop);};const start=()=>{if(disposed||runningRef.current)return;if(cfg.stopMotionInEditor&&isEditorCanvas()){renderOnce(0);return;}runningRef.current=true;acc=FRAME;loop();};const stop=()=>{runningRef.current=false;cancelAnimationFrame(rafRef.current);};const onVis=()=>document.hidden?stop():start();document.addEventListener("visibilitychange",onVis);const io=new IntersectionObserver(entries=>{const vis=entries[0]?.isIntersecting;vis?start():stop();},{root:null,threshold:0});// Safety: container might be gone by now
if(containerRef.current)io.observe(containerRef.current);renderOnce(0);start();const onResizeCanvas=()=>{if(!containerRef.current)return;const rect=containerRef.current.getBoundingClientRect();// Avoid 0-size errors
const w=Math.max(1,Math.round(rect.width));const h=Math.max(1,Math.round(rect.height));camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,MAX_DPR));renderer.setSize(w,h);if(composer){composer.setPixelRatio(Math.min(window.devicePixelRatio||1,MAX_DPR));composer.setSize(w,h);if(bloomPass?.setSize)bloomPass.setSize(w,h);}syncOverlay();acc=FRAME;renderOnce(0);};window.addEventListener("resize",onResizeCanvas);try{roContainer=new ResizeObserver(onResizeCanvas);if(containerRef.current)roContainer.observe(containerRef.current);}catch{roContainer=null;}// --- CLEANUP FUNCTION ---
cleanup=()=>{stop();window.removeEventListener("resize",onResizeCanvas);document.removeEventListener("visibilitychange",onVis);io.disconnect();try{window.removeEventListener("resize",onResize);window.removeEventListener("scroll",onScroll);if(window.top){window.top.removeEventListener("resize",onResize);window.top.removeEventListener("scroll",onScroll);}}catch{}try{roLocal?.disconnect();}catch{}try{roHost?.disconnect();}catch{}try{roContainer?.disconnect();}catch{}// Remove overlay
try{if(overlayHost&&overlayHost.parentNode)overlayHost.parentNode.removeChild(overlayHost);}catch{}// Remove DOM listeners
if(renderer&&renderer.domElement){try{renderer.domElement.removeEventListener("click",onClick);renderer.domElement.removeEventListener("mousemove",onMouseMove);renderer.domElement.removeEventListener("mousedown",onDown);renderer.domElement.removeEventListener("mouseup",onUp);renderer.domElement.removeEventListener("mouseleave",onLeave);renderer.domElement.removeEventListener("touchstart",onDown);renderer.domElement.removeEventListener("touchend",onUp);}catch{}// Remove Canvas
if(renderer.domElement.parentNode){renderer.domElement.parentNode.removeChild(renderer.domElement);}renderer.dispose();}try{controls.removeEventListener("start",onDragStart);controls.removeEventListener("end",onDragEnd);if(onControlsChange)controls.removeEventListener("change",onControlsChange);}catch{}controls.dispose();try{HOST_DOC.removeEventListener("scroll",onScroll,{capture:true});}catch{}try{composer?.dispose?.();}catch{}activeTrails.forEach(t=>{t.mesh.geometry.dispose();t.mesh.material.dispose();});disposeScene(scene);};};run().catch(()=>{if(!disposed)setLoading(false);});return()=>{disposed=true;try{cleanup?.();}catch{}};},[props.autoRotateSpeed,props.pointSize,props.tileDeg,props.zoom,props.pointColor,props.labelColor,props.pinDotColor,props.pinPanelBgColor,props.pinPanelBgOpacity,props.pinPanelBorderColor,props.backOpacity,props.fillColor,props.fillOpacity,props.showLabels,props.pinSize,props.haloScale,JSON.stringify(props.pins),JSON.stringify(props.labelFont),props.labelFontSize,props.preloaderTheme,props.initialRotationY,props.stopMotionInEditor,props.showTrails,props.trailColor,props.enableBloom,props.enableChromaticAberration,props.enableFilm,props.enableGlitch,props.fxIntensity]);return /*#__PURE__*/_jsxs("div",{style:{width:"100%",height:"100%",position:"relative",overflow:"hidden"},children:[loading&&/*#__PURE__*/_jsx(Preloader,{progress:progress,theme:cfg.preloaderTheme}),/*#__PURE__*/_jsx("div",{ref:containerRef,style:{width:"100%",height:"100%",position:"relative",overflow:"hidden"}})]});}// ================= Geo =================
async function getLand(){if(LAND_POLYS&&LAND_GEO_POLYS)return{polys:LAND_POLYS,geoPolys:LAND_GEO_POLYS};const urls=["https://cdn.jsdelivr.net/npm/world-atlas@2/land-110m.json","https://unpkg.com/world-atlas@2/land-110m.json"];let topo=null;for(const u of urls){try{const r=await fetch(u,{cache:"force-cache"});if(r.ok){topo=await r.json();break;}}catch{}}if(!topo)throw new Error("land-110m.json unavailable");const{feature}=await import(/* @vite-ignore */URL_TOPO);const land=feature(topo,topo.objects.land);const polys=[];const geoPolys=[];(land.features||[]).forEach(f=>{const g=f.geometry;if(!g)return;if(g.type==="Polygon"){polys.push(g.coordinates.map((ring,idx)=>toRing(ring,idx)));geoPolys.push({type:"Polygon",coordinates:g.coordinates});}else if(g.type==="MultiPolygon"){g.coordinates.forEach(poly=>{polys.push(poly.map((ring,idx)=>toRing(ring,idx)));geoPolys.push({type:"Polygon",coordinates:poly});});}});LAND_POLYS=polys;LAND_GEO_POLYS=geoPolys;return{polys,geoPolys};}function toRing(ring,idx){if(idx>0){const out=new Float32Array((ring.length+1)*2);let k=0;for(let i=0;i<ring.length;i++){out[k++]=ring[i][0];out[k++]=ring[i][1];}const last=ring[ring.length-1];out[k++]=last[0];out[k++]=last[1];return out.subarray(0,k);}const L=ring.length,target=3e3,step=L>target?Math.floor(L/target):1;const out=new Float32Array((Math.ceil(L/step)+1|0)*2);let k=0;for(let i=0;i<L;i+=step){out[k++]=ring[i][0];out[k++]=ring[i][1];}const last=ring[L-1];out[k++]=last[0];out[k++]=last[1];return out.subarray(0,k);}function filterNonPolarPolys(polys,geoPolys){const outP=[],outG=[];for(let i=0;i<polys.length;i++){const outer=polys[i][0];if(!outer||outer.length<4)continue;const bbox=boundsOfRing(outer);const w=bbox.maxLon-bbox.minLon;const avgLat=(bbox.minLat+bbox.maxLat)/2;if(w>300&&Math.abs(avgLat)>60)continue;outP.push(polys[i]);outG.push(geoPolys[i]);}return{polys:outP,geoPolys:outG};}// ================= Workers =================
function buildEdgesInWorker(polys,densityDeg){return new Promise((resolve,reject)=>{const payload=polys.map(poly=>poly.map(ring=>new Float32Array(ring)));const src=`
            function wrapLon(lon){ return ((lon + 540) % 360) - 180; }
            function sampleEdgeFlat(ring, maxDegStep){
                var out = [];
                for (var i=0;i<ring.length-2;i+=2){
                    var lon1 = ring[i],   lat1 = ring[i+1];
                    var lon2 = ring[i+2], lat2 = ring[i+3];
                    var dLon = lon2 - lon1, lon2n = lon2;
                    if (Math.abs(dLon)>180){ lon2n += dLon>0?-360:360; dLon = lon2n - lon1; }
                    var dLat = lat2 - lat1;
                    var maxSpan = Math.max(Math.abs(dLon), Math.abs(dLat));
                    var steps = Math.max(1, Math.ceil(maxSpan / maxDegStep));
                    for (var s=0;s<=steps;s++){
                        var t = s/steps;
                        var lon = lon1 + dLon*t;
                        var lat = lat1 + dLat*t;
                        out.push(wrapLon(lon), lat);
                    }
                }
                return new Float32Array(out);
            }
            function lonLatToVec3(lon,lat,r){
                if (r === void 0) r = 1;
                var phi = (90 - lat) * Math.PI/180;
                var theta = (lon + 180) * Math.PI/180;
                return [-Math.sin(phi) * Math.cos(theta), Math.cos(phi), Math.sin(phi) * Math.sin(theta)];
            }
            onmessage = function(e){
                var densityDeg = e.data.densityDeg, polysIn = e.data.polysIn;
                var edgeOut = [];
                for (var p=0;p<polysIn.length;p++){
                    var poly = polysIn[p];
                    for (var r=0;r<poly.length;r++){
                        var sampled = sampleEdgeFlat(poly[r], Math.max(0.2, densityDeg));
                        for (var i=0;i<sampled.length;i+=2){
                            var v = lonLatToVec3(sampled[i], sampled[i+1], 1);
                            edgeOut.push(v[0],v[1],v[2]);
                        }
                    }
                }
                var arr = new Float32Array(edgeOut);
                postMessage({ ok:true, edge:arr }, [arr.buffer]);
            };
        `;const blob=new Blob([src],{type:"application/javascript"});const url=URL.createObjectURL(blob);const worker=new Worker(url);worker.onmessage=e=>{URL.revokeObjectURL(url);worker.terminate();const msg=e.data;if(msg&&msg.ok)resolve(msg.edge);else reject(new Error("worker failed"));};worker.onerror=err=>{URL.revokeObjectURL(url);worker.terminate();reject(err);};worker.postMessage({densityDeg,polysIn:payload});});}function buildFillTileInWorker(geoPolys,tileDeg){return new Promise((resolve,reject)=>{const payload=JSON.parse(JSON.stringify(geoPolys));const src=`
var PI=Math.PI;
function wrap180(lon){ return ((lon+540)%360)-180; }
function vec3(lon,lat){
  var phi=(90-lat)*PI/180, th=(lon+180)*PI/180;
  return [-Math.sin(phi)*Math.cos(th), Math.cos(phi), Math.sin(phi)*Math.sin(th)];
}
function unwrapRing(ring, refLon){
  var out=new Array(ring.length), prev=null;
  for(var i=0;i<ring.length;i++){
    var L=ring[i][0], A=ring[i][1];
    var d=L-refLon;
    if(d>180) L-=360; else if(d<-180) L+=360;
    if(prev){
      var step=L-prev[0];
      if(step>180) L-=360; else if(step<-180) L+=360;
    }
    out[i]=[L,A]; prev=out[i];
  }
  return out;
}
function pointInRing(pt, ring){
  var x=pt[0], y=pt[1], inside=false, n=ring.length;
  for(var i=0,j=n-1;i<n;j=i++){
    var xi=ring[i][0], yi=ring[i][1];
    var xj=ring[j][0], yj=ring[j][1];
    var denom=yj-yi; if(denom===0) continue;
    var inter=((yi>y)!==(yj>y)) && (x < (xj-xi)*(y-yi)/denom + xi);
    if(inter) inside=!inside;
  }
  return inside;
}
function containsUnwrapped(poly, refLon, lon, lat){
  var rings=poly.coordinates; if(!rings||!rings.length) return false;
  var r0=unwrapRing(rings[0], refLon);
  var pt=[lon,lat];
  if(!pointInRing(pt, r0)) return false;
  for(var k=1;k<rings.length;k++){
    var rk=unwrapRing(rings[k], refLon);
    if(pointInRing(pt, rk)) return false;
  }
  return true;
}
function bbox(r){
  var minLon=1e9,maxLon=-1e9,minLat=90,maxLat=-90;
  for(var i=0;i<r.length;i++){
    var L=r[i][0], A=r[i][1];
    if(L<minLon)minLon=L; if(L>maxLon)maxLon=L;
    if(A<minLat)minLat=A; if(A>maxLat)maxLat=A;
  }
  return {minLon,maxLon,minLat,maxLat};
}

onmessage=function(e){
  var geos=e.data.geos, step=Math.max(0.2, Math.min(6.0, e.data.tileDeg||1.0));
  var out=[];
  for(var p=0;p<geos.length;p++){
    var r0 = unwrapRing(geos[p].coordinates[0], 0);
    var bb = bbox(r0);
    var refLon = (bb.minLon+bb.maxLon)/2;
    r0 = unwrapRing(geos[p].coordinates[0], refLon);
    bb = bbox(r0);

    var latStart = Math.floor((bb.minLat-1)/step)*step;
    var latEnd   = Math.ceil((bb.maxLat+1)/step)*step;

    for(var lat=latStart; lat<=latEnd; lat+=step){
      var odd = Math.round(Math.abs(lat/step))%2;
      var lonStart = Math.floor((bb.minLon-1)/step)*step + (odd? step*0.5 : 0);
      var lonEnd   = Math.ceil((bb.maxLon+1)/step)*step;
      for(var lon=lonStart; lon<=lonEnd; lon+=step){
        var llLon = lon, llLat = Math.max(-90, Math.min(90, lat));
        if(containsUnwrapped(geos[p], refLon, llLon, llLat)){
          var v = vec3(wrap180(llLon), llLat);
          out.push(v[0],v[1],v[2]);
        }
      }
    }
  }
  var arr=new Float32Array(out);
  postMessage({ok:true, fill:arr}, [arr.buffer]);
};
`;const blob=new Blob([src],{type:"application/javascript"});const url=URL.createObjectURL(blob);const worker=new Worker(url);worker.onmessage=e=>{URL.revokeObjectURL(url);worker.terminate();const msg=e.data;if(msg&&msg.ok)resolve(msg.fill);else reject(new Error("worker failed"));};worker.onerror=err=>{URL.revokeObjectURL(url);worker.terminate();reject(err);};worker.postMessage({geos:payload,tileDeg});});}// ================= Helpers =================
function boundsOfRing(ring){let minLon=180,maxLon=-180,minLat=90,maxLat=-90;for(let i=0;i<ring.length;i+=2){const x=ring[i],y=ring[i+1];if(x<minLon)minLon=x;if(x>maxLon)maxLon=x;if(y<minLat)minLat=y;if(y>maxLat)maxLat=y;}return{minLon,maxLon,minLat,maxLat};}function lonLatToVec3(lon,lat,r=1){const phi=THREE.MathUtils.degToRad(90-lat);const theta=THREE.MathUtils.degToRad(lon+180);return new THREE.Vector3(-r*Math.sin(phi)*Math.cos(theta),r*Math.cos(phi),r*Math.sin(phi)*Math.sin(theta));}function fontFamilyFromControl(font,fallback="system-ui,-apple-system,Segoe UI,Roboto,sans-serif"){if(!font)return fallback;if(typeof font==="string")return font;return font.family||font.fontFamily||fallback;}function addPin(group,pin,tex,CSS2DObject,labelColor,pinDotColor,panelBgColor,panelBgOpacity,panelBorderColor,labelFont,labelFontSize,pinSize,haloScale){const pos=lonLatToVec3(pin.lon,pin.lat,1);const g=new THREE.Group;g.__pin=pin;g.position.copy(pos);// pin
const sphere=new THREE.Mesh(new THREE.SphereGeometry(pinSize,16,16),new THREE.MeshBasicMaterial({color:new THREE.Color(pinDotColor)}));g.add(sphere);// halo
const halo=new THREE.Sprite(new THREE.SpriteMaterial({color:new THREE.Color(pinDotColor),map:tex,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false}));const haloSize=pinSize*haloScale;halo.scale.set(haloSize,haloSize,haloSize);g.add(halo);// label (DOM). Address supports \n
if((pin.name||pin.address||pin.phone)&&CSS2DObject){const el=document.createElement("div");const bg=hexToRgba(panelBgColor,panelBgOpacity);const ff=fontFamilyFromControl(labelFont);el.style.cssText=`width:280px;max-width:280px;`+`white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-break:anywhere;hyphens:auto;`+`padding:12px;border-radius:8px;background:${bg};backdrop-filter:blur(6px);`+`border:1px solid ${panelBorderColor};color:${labelColor};`+`pointer-events:none;font-family:${ff};font-size:${labelFontSize}px;line-height:1.35;`;const nl2br=s=>s.replace(/\n/g,"<br/>");const nameHTML=pin.name?`<b>${pin.name}</b><br/>`:"";const addrHTML=pin.address?`${nl2br(pin.address)}<br/>`:"";const phoneHTML=pin.phone??"";el.innerHTML=`${nameHTML}${addrHTML}${phoneHTML}`;const labelObj=new CSS2DObject(el);labelObj.position.set(0,.08,0);g.__labelObj=labelObj;g.add(labelObj);}group.add(g);return{g,pos};}function makeHaloTexture(size=128){const c=document.createElement("canvas");c.width=c.height=size;const x=c.getContext("2d");const g=x.createRadialGradient(size/2,size/2,0,size/2,size/2,size/2);g.addColorStop(0,"rgba(255,255,255,0.25)");g.addColorStop(.35,"rgba(255,255,255,0.1)");g.addColorStop(1,"rgba(255,255,255,0)");x.fillStyle=g;x.fillRect(0,0,size,size);const tex=new THREE.CanvasTexture(c);tex.minFilter=THREE.LinearFilter;tex.magFilter=THREE.LinearFilter;return tex;}function makeCircleDotTexture(size=64){const c=document.createElement("canvas");c.width=c.height=size;const x=c.getContext("2d");x.clearRect(0,0,size,size);const r=size/2;const g=x.createRadialGradient(r,r,r*.82,r,r,r);g.addColorStop(0,"rgba(255,255,255,1)");g.addColorStop(1,"rgba(255,255,255,0)");x.fillStyle=g;x.beginPath();x.arc(r,r,r-.5,0,Math.PI*2);x.closePath();x.fill();const tex=new THREE.CanvasTexture(c);tex.minFilter=THREE.LinearFilter;tex.magFilter=THREE.LinearFilter;tex.anisotropy=1;tex.generateMipmaps=false;return tex;}function hexToRgba(input,a=1){try{if(/^rgba?\(/i.test(input))return input.replace(/rgba?\(([^)]+)\)/i,(_,body)=>{const p=body.split(",").map(s=>parseFloat(s.trim()));const[r,g,b]=p;return`rgba(${r},${g},${b},${Math.max(0,Math.min(1,a))})`;});const m=input.replace("#","");const s=m.length===3?m.split("").map(x=>x+x).join(""):m;const n=parseInt(s,16);const r=n>>16&255,g=n>>8&255,b=n&255;return`rgba(${r},${g},${b},${Math.max(0,Math.min(1,a))})`;}catch{return`rgba(255,255,255,${a})`;}}function disposeScene(scene){scene.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material){if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material.dispose();}});}function makePointsMat(color,size,backOpacity,dotTexture,overrideOpacity){const material=new THREE.PointsMaterial({color:new THREE.Color(color),size,sizeAttenuation:true,depthWrite:false,transparent:true,map:dotTexture,alphaTest:0,opacity:overrideOpacity??1});material.toneMapped=false;material.precision="mediump";material.onBeforeCompile=shader=>{shader.uniforms.uCamPos={value:new THREE.Vector3};shader.uniforms.uBackOpacity={value:backOpacity};shader.vertexShader=shader.vertexShader.replace("#include <common>","#include <common>\n varying vec3 vWorldPos;\n uniform vec3 uCamPos;").replace("#include <begin_vertex>","#include <begin_vertex>\n vWorldPos = (modelMatrix * vec4(transformed,1.0)).xyz;").replace("#include <project_vertex>",`#include <project_vertex>
                 float ndv = dot(normalize(uCamPos - vWorldPos), normalize(vWorldPos));
                 gl_PointSize *= mix(0.6, 1.0, smoothstep(0.0, 0.25, ndv));`);shader.fragmentShader=shader.fragmentShader.replace("#include <common>","#include <common>\n varying vec3 vWorldPos; uniform vec3 uCamPos; uniform float uBackOpacity;").replace("#include <clipping_planes_fragment>",`#include <clipping_planes_fragment>
                 float ndHem; {
                   vec3 viewDir = normalize(uCamPos - vWorldPos);
                   vec3 normalDir = normalize(vWorldPos); // sphere normal
                   ndHem = dot(viewDir, normalDir); // >0 front
                 }`).replace("#include <color_fragment>",`#include <color_fragment>
                 diffuseColor.a *= mix(uBackOpacity, 1.0, smoothstep(0.0, 0.25, ndHem));`);material.userData.shader=shader;};return material;}function limitPoints(src,cap){const n=src.length/3;if(n<=cap)return src;const idxs=new Uint32Array(n);for(let i=0;i<n;i++)idxs[i]=i;for(let i=n-1;i>0;i--){const j=Math.random()*(i+1)|0;const t=idxs[i];idxs[i]=idxs[j];idxs[j]=t;}const out=new Float32Array(cap*3);for(let k=0;k<cap;k++){const i=idxs[k]*3;out[k*3+0]=src[i+0];out[k*3+1]=src[i+1];out[k*3+2]=src[i+2];}return out;}function buildEdgesSync(polys,densityDeg){const edgeOut=[];for(const poly of polys){for(const ring of poly){const sampled=sampleEdgeFlat(ring,Math.max(.2,densityDeg));for(let i=0;i<sampled.length;i+=2){const v=lonLatToVec3Sync(sampled[i],sampled[i+1],1);edgeOut.push(v[0],v[1],v[2]);}}}return{edge:new Float32Array(edgeOut)};function sampleEdgeFlat(ring,maxDegStep){const out=[];for(let i=0;i<ring.length-2;i+=2){let lon1=ring[i],lat1=ring[i+1];let lon2=ring[i+2],lat2=ring[i+3];let dLon=lon2-lon1;if(Math.abs(dLon)>180){lon2+=dLon>0?-360:360;dLon=lon2-lon1;}const dLat=lat2-lat1;const maxSpan=Math.max(Math.abs(dLon),Math.abs(dLat));const steps=Math.max(1,Math.ceil(maxSpan/maxDegStep));for(let s=0;s<=steps;s++){const t=s/steps;const lon=lon1+dLon*t;const lat=lat1+dLat*t;out.push((lon+540)%360-180,lat);}}return new Float32Array(out);}function lonLatToVec3Sync(lon,lat,r=1){const phi=(90-lat)*Math.PI/180;return[-Math.sin(phi)*Math.cos((lon+180)*Math.PI/180),Math.cos(phi),Math.sin(phi)*Math.sin((lon+180)*Math.PI/180)];}}// ================= Controls =================
addPropertyControls(Globe_Pins,{autoRotateSpeed:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.autoRotateSpeed,min:.01,max:.15,step:.01,title:"Auto Rotate"},initialRotationY:{type:ControlType.Number,title:"Start From",defaultValue:DEFAULT_PROPS.initialRotationY,min:-360,max:360,step:1,unit:"\xb0",displayStepper:true},stopMotionInEditor:{type:ControlType.Boolean,title:"Stop Motion in Editor",defaultValue:DEFAULT_PROPS.stopMotionInEditor},zoom:{type:ControlType.Boolean,defaultValue:DEFAULT_PROPS.zoom,title:"Zoom"},pointSize:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.pointSize,min:.002,max:.05,step:.001,title:"Land Dot Size"},tileDeg:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.tileDeg,min:.2,max:6,step:.1,title:"Tile Step (deg)"},pointColor:{type:ControlType.Color,defaultValue:DEFAULT_PROPS.pointColor,title:"Edge Color"},labelFont:{type:ControlType.Font,defaultValue:{family:"Inter",style:"Regular"},title:"Label Font"},labelFontSize:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.labelFontSize,min:8,max:32,step:1,title:"Label Size"},labelColor:{type:ControlType.Color,defaultValue:DEFAULT_PROPS.labelColor,title:"Label Color"},fillColor:{type:ControlType.Color,defaultValue:DEFAULT_PROPS.fillColor,title:"Fill Color"},fillOpacity:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.fillOpacity,min:0,max:1,step:.01,title:"Fill Opacity"},backOpacity:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.backOpacity,min:0,max:1,step:.01,title:"Opacity Backside"},showLabels:{type:ControlType.Boolean,defaultValue:DEFAULT_PROPS.showLabels,title:"Show Labels"},pinSize:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.pinSize,min:.004,max:.1,step:.001,title:"Pin Size"},haloScale:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.haloScale,min:0,max:20,step:.5,title:"Halo Scale"},pinDotColor:{type:ControlType.Color,defaultValue:DEFAULT_PROPS.pinDotColor,title:"Pin Color"},pinPanelBgColor:{type:ControlType.Color,defaultValue:DEFAULT_PROPS.pinPanelBgColor,title:"Panel BG"},pinPanelBgOpacity:{type:ControlType.Number,defaultValue:DEFAULT_PROPS.pinPanelBgOpacity,min:0,max:1,step:.01,title:"Panel BG Opacity"},pinPanelBorderColor:{type:ControlType.Color,defaultValue:DEFAULT_PROPS.pinPanelBorderColor,title:"Panel Border"},pins:{type:ControlType.Array,propertyControl:{type:ControlType.Object,controls:{lon:{type:ControlType.Number,defaultValue:0},lat:{type:ControlType.Number,defaultValue:0},name:{type:ControlType.String},address:{type:ControlType.String,defaultValue:"",displayTextArea:true,title:"Address"},phone:{type:ControlType.String}}},defaultValue:DEFAULT_PROPS.pins,title:"Pins"},showTrails:{type:ControlType.Boolean,title:"Show Trails",defaultValue:DEFAULT_PROPS.showTrails},trailColor:{type:ControlType.Color,title:"Trail Color",defaultValue:DEFAULT_PROPS.trailColor,hidden:props=>!props.showTrails},preloaderTheme:{type:ControlType.Enum,options:["Dark","Light"],optionTitles:["Dark","Light"],defaultValue:DEFAULT_PROPS.preloaderTheme,title:"Preloader"},enableBloom:{type:ControlType.Boolean,title:"Bloom",defaultValue:DEFAULT_PROPS.enableBloom},enableChromaticAberration:{type:ControlType.Boolean,title:"Chromatic",defaultValue:DEFAULT_PROPS.enableChromaticAberration},enableFilm:{type:ControlType.Boolean,title:"Film/Scan",defaultValue:DEFAULT_PROPS.enableFilm},enableGlitch:{type:ControlType.Boolean,title:"Glitch",defaultValue:DEFAULT_PROPS.enableGlitch},fxIntensity:{type:ControlType.Number,title:"FX Intensity",defaultValue:DEFAULT_PROPS.fxIntensity,min:0,max:1,step:.01}});
export const __FramerMetadata__ = {"exports":{"Globe_PinsProps":{"type":"tsType","annotations":{"framerContractVersion":"1"}},"Pin":{"type":"tsType","annotations":{"framerContractVersion":"1"}},"default":{"type":"reactComponent","name":"Globe_Pins","slots":[],"annotations":{"framerIntrinsicWidth":"600","framerSupportedLayoutWidth":"any-prefer-fixed","framerSupportedLayoutHeight":"any-prefer-fixed","framerIntrinsicHeight":"600","framerContractVersion":"1"}},"__FramerMetadata__":{"type":"variable"}}}
//# sourceMappingURL=./Globe_Pins.map