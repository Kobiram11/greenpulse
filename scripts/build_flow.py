"""Generate the importable FlowFuse Dashboard 2 flow; no credentials embedded."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = '''<template>
<div class="gp" v-if="msg?.payload">
  <header><h1>GreenPulse</h1><p>Live plant conditions and cloud care advice</p></header>
  <p><strong>MQTT:</strong> {{ msg.payload.broker || 'unknown' }} ·
     <strong>Device:</strong> {{ msg.payload.device || 'unknown' }} ·
     <strong>Backend:</strong> {{ msg.payload.backend || 'waiting' }}</p>
  <p>Last sensor message: {{ msg.payload.sensors?.received || 'Waiting for device' }}</p>
  <h2>Sensor readings</h2>
  <table><thead><tr><th>Measurement</th><th>Value</th></tr></thead><tbody>
    <tr v-for="row in rows" :key="row[0]"><td>{{ row[0] }}</td><td>{{ row[1] ?? 'Unavailable' }} {{ row[1] == null ? '' : row[2] }}</td></tr>
  </tbody></table>
  <h2>Care advice</h2>
  <p><strong>Priority:</strong> {{ msg.payload.care?.data?.priority || 'unknown' }}
     <span v-if="msg.payload.care"> · LLM: {{ msg.payload.care.data.llm_status }}</span></p>
  <p>{{ msg.payload.care?.data?.care_message || 'Waiting for backend response' }}</p>
  <blockquote v-if="msg.payload.care?.data?.quote">{{ msg.payload.care.data.quote }}</blockquote>
  <h3>Weather</h3><p>{{ msg.payload.care?.data?.weather_summary || 'Waiting' }}</p>
  <h3>Notifications</h3><p>{{ msg.payload.care?.data?.notification_summary || 'Waiting' }}</p>
  <h2>MQTT evidence</h2>
  <section v-for="key in ['sensors','status','llm-input','care','alerts']" :key="key">
    <h3>{{ key }}</h3>
    <p class="topic">{{ msg.payload[key]?.topic || 'No message yet' }}</p>
    <p>Received: {{ msg.payload[key]?.received || '—' }}</p>
    <pre>{{ pretty(msg.payload[key]?.data) }}</pre>
  </section>
</div>
<p v-else>Waiting for MQTT. Configure the AWS broker and dashboard certificates.</p>
</template>
<script>
export default {
  computed: {
    rows() {
      const d = this.msg?.payload?.sensors?.data || {};
      return [['Soil moisture',d.soil?.moisture,'%'],['Soil temperature',d.soil?.temperature,'°C'],
        ['pH',d.soil?.ph,''],['Electrical conductivity',d.soil?.ec,'µS/cm'],
        ['Nitrogen',d.soil?.n,'mg/kg'],['Phosphorus',d.soil?.p,'mg/kg'],
        ['Potassium',d.soil?.k,'mg/kg'],['Air temperature',d.air?.temperature,'°C'],
        ['Air humidity',d.air?.humidity,'%']];
    }
  },
  methods: { pretty(value) { return value ? JSON.stringify(value,null,2) : 'Waiting'; } }
};
</script>
<style>
.gp { max-width:1000px; margin:0 auto; padding:16px; color:#17392c; }
.gp h1 { font-size:32px; margin-bottom:8px; }
.gp h2 { margin-top:28px; border-bottom:1px solid #d7e4dc; padding-bottom:8px; }
.gp table { width:100%; border-collapse:collapse; }
.gp th,.gp td { text-align:left; padding:10px; border-bottom:1px solid #d7e4dc; }
.gp pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#f2f6f3; padding:16px; max-height:420px; overflow:auto; }
.gp .topic { overflow-wrap:anywhere; font-family:monospace; }
.gp blockquote { border-left:3px solid #3b8c64; padding-left:16px; }
</style>'''

aggregate = '''let state=flow.get('greenpulse') || {};
const now=Date.now();
if (msg.status) {
  state.broker=msg.status.text || 'unknown';
} else if (msg.topic) {
  const key=msg.topic.split('/').pop();
  if (['sensors','status','llm-input','care','alerts'].includes(key)) {
    let data=msg.payload;
    try { if (typeof data==='string') data=JSON.parse(data); }
    catch(e) { node.warn('Invalid MQTT JSON'); return null; }
    if (!data || typeof data!=='object') return null;
    state[key]={topic:msg.topic,data,received:new Date(now).toISOString(),received_ms:now};
  }
}
const last=state.sensors?.received_ms || 0;
const sensorTs=(state.sensors?.data?.ts || 0)*1000;
const sensorFresh=now-sensorTs<45000 && sensorTs-now<60000;
state.device=last && now-last<45000 && sensorFresh && state.status?.data?.online!==false ? 'online' : 'offline / stale';
const expiry=state.care?.data?.expires_ts || 0;
state.backend=expiry*1000>now ? 'response current' : 'waiting / stale';
flow.set('greenpulse',state);
return {payload:state};'''

nodes = [
 {"id":"gp-tab","type":"tab","label":"GreenPulse AWS","disabled":False,"info":"Configure AWS endpoint, DEVICE_ID, client ID and TLS certificate files. Requires @flowfuse/node-red-dashboard."},
 {"id":"gp-broker","type":"mqtt-broker","name":"AWS IoT Core","broker":"${AWS_IOT_ENDPOINT}","port":"8883","clientid":"${NODE_RED_CLIENT_ID}","autoConnect":True,"usetls":True,"tls":"gp-tls","protocolVersion":"4","keepalive":"60","cleansession":True,"autoUnsubscribe":True},
 {"id":"gp-tls","type":"tls-config","name":"Dashboard certificate (configure)","cert":"/data/certs/dashboard-certificate.pem.crt","key":"/data/certs/dashboard-private.pem.key","ca":"/data/certs/AmazonRootCA1.pem","certname":"","keyname":"","caname":"","servername":"","verifyservercert":True,"alpnprotocol":""},
 {"id":"gp-base","type":"ui-base","name":"GreenPulse","path":"/dashboard","appIcon":"","includeClientData":True,"acceptsClientConfig":["ui-notification","ui-control"],"showPathInSidebar":False,"navigationStyle":"default","titleBarStyle":"default","showReconnectNotification":True,"notificationDisplayTime":1,"showDisconnectNotification":True},
 {"id":"gp-theme","type":"ui-theme","name":"GreenPulse","colors":{"surface":"#ffffff","primary":"#24704b","bgPage":"#f5f8f5","groupBg":"#ffffff","groupOutline":"#d7e4dc"},"sizes":{"density":"default","pagePadding":"12px","groupGap":"12px","groupBorderRadius":"4px","widgetGap":"12px"}},
 {"id":"gp-page","type":"ui-page","name":"Plant monitor","ui":"gp-base","path":"/plant","icon":"eco","layout":"grid","theme":"gp-theme","breakpoints":[{"name":"Default","px":"0","cols":"3"},{"name":"Tablet","px":"576","cols":"6"},{"name":"Desktop","px":"1024","cols":"12"}],"order":1,"className":"","visible":True,"disabled":False},
 {"id":"gp-group","type":"ui-group","name":"GreenPulse live data","page":"gp-page","width":"12","height":"1","order":1,"showTitle":False,"className":"","visible":True,"disabled":False,"groupType":"default"},
 {"id":"gp-input","type":"mqtt in","z":"gp-tab","name":"All device topics","topic":"greenpulse/device/${DEVICE_ID}/#","qos":"1","datatype":"auto-detect","broker":"gp-broker","nl":False,"rap":True,"rh":0,"inputs":0,"x":180,"y":100,"wires":[["gp-aggregate","gp-debug"]]},
 {"id":"gp-status","type":"status","z":"gp-tab","name":"Broker connection","scope":["gp-input"],"x":180,"y":160,"wires":[["gp-aggregate"]]},
 {"id":"gp-tick","type":"inject","z":"gp-tab","name":"Refresh stale status","props":[{"p":"payload"}],"repeat":"5","once":True,"onceDelay":"1","payload":"","payloadType":"date","x":180,"y":220,"wires":[["gp-aggregate"]]},
 {"id":"gp-aggregate","type":"function","z":"gp-tab","name":"Latest readings and payloads","func":aggregate,"outputs":1,"timeout":0,"noerr":0,"initialize":"","finalize":"","libs":[],"x":460,"y":160,"wires":[["gp-template"]]},
 {"id":"gp-template","type":"ui-template","z":"gp-tab","group":"gp-group","page":"","ui":"","name":"GreenPulse dashboard","order":1,"width":"12","height":"0","head":"","format":template,"storeOutMessages":True,"passthru":False,"resendOnRefresh":True,"templateScope":"local","className":"","x":740,"y":160,"wires":[[]]},
 {"id":"gp-debug","type":"debug","z":"gp-tab","name":"MQTT subscribed payload","active":True,"tosidebar":True,"console":False,"tostatus":False,"complete":"true","targetType":"full","x":470,"y":80,"wires":[]}
]
(root / "node-red/greenpulse-flow.json").write_text(json.dumps(nodes, indent=2))
print("Generated node-red/greenpulse-flow.json")
