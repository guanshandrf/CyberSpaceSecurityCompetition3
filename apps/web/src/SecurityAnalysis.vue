<script setup>
import { computed } from 'vue'
import { analyzeSecurity } from './securityAnalysis.js'

const props = defineProps({
  records: { type: Array, required: true },
  trace: { type: String, required: true },
  callId: { type: String, required: true },
  name: { type: String, required: true },
  done: Boolean,
  interrupted: Boolean,
  noTool: Boolean,
})
const report = computed(() => analyzeSecurity(props.records, { done: props.done, interrupted: props.interrupted, noTool: props.noTool }))
</script>

<template>
  <details class="security-analysis" :data-tone="report.tone">
    <summary><span>▤ 详细分析报告</span><small>{{ report.title }}</small></summary>
    <div class="analysis-content">
      <p class="analysis-method">基于本次已记录的脱敏审计自动整理；不额外调用模型，不分析或展示敏感原文。</p>
      <div class="analysis-verdict"><span>分析结论</span><strong>{{ report.title }}</strong><p>{{ report.conclusion }}</p></div>
      <dl class="analysis-facts">
        <div><dt>工具</dt><dd>{{ name }}</dd></div>
        <div><dt>记录最高风险</dt><dd>{{ report.risk }}</dd></div>
        <div><dt>证据数量</dt><dd>{{ report.recordCount }} 条（含 {{ report.lifecycleCount }} 条关联注册记录）</dd></div>
        <div><dt>本次记录耗时范围</dt><dd>{{ report.timing }}</dd></div>
      </dl>
      <p>{{ report.riskNote }}</p><p>{{ report.timingNote }}</p>
      <h4>1. 风险与判定依据</h4>
      <div v-for="issue in report.issues" :key="issue.name" class="analysis-issue"><strong>{{ issue.name }}</strong><p>{{ issue.meaning }}</p><small>证据：{{ issue.evidence.map(id => `#${id}`).join('、') }}</small></div>
      <p v-if="!report.issues.length">现有记录没有可归类的限制或风险命中原因；不把“未发现”解释为“不存在风险”。</p>
      <h4>2. 防护链与覆盖情况</h4>
      <div class="analysis-coverage"><div v-for="item in report.coverage" :key="item.gate"><strong>{{ item.gate }}</strong><span>{{ item.status }} · {{ item.count }} 条</span><p>{{ item.note }}</p></div></div>
      <h4>3. 可追溯证据</h4>
      <ol class="analysis-evidence"><li v-for="item in report.evidence" :key="item.id"><strong>#{{ item.id }} · {{ item.gate }} · {{ item.action }}</strong><p>{{ item.stage }} · {{ item.timestamp }}</p><p v-for="reason in item.reasons" :key="reason.code">{{ reason.text }} <code>{{ reason.code }}</code></p></li></ol>
      <p v-if="!report.evidence.length">尚无可关联的审计证据。</p>
      <p class="analysis-identifiers">trace {{ trace }}<br>call {{ callId || '无工具调用标识' }}</p>
      <h4>4. 待核实事项与建议</h4>
      <ul v-if="report.gaps.length" class="analysis-gaps"><li v-for="gap in report.gaps" :key="gap">{{ gap }}</li></ul>
      <ul><li v-for="advice in report.advice" :key="advice">{{ advice }}</li></ul>
      <p class="analysis-boundary">覆盖边界：仅解释受控工具的已记录行为；不能证明工具代码安全、任务正确完成或全面抵御提示注入。此报告不会更改防护策略或执行权限。</p>
    </div>
  </details>
</template>
