<script setup>
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  placeholder: { type: String, default: '输入后按回车，可一次粘贴多个，用逗号分隔' },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])
const input = ref('')

function add() {
  if (props.disabled) return
  const values = input.value.split(/[,，、\s]+/).map((item) => item.trim()).filter(Boolean)
  if (!values.length) return
  const next = [...props.modelValue]
  for (const value of values) {
    if (!next.includes(value)) next.push(value)
  }
  emit('update:modelValue', next)
  input.value = ''
}

function remove(value) {
  emit('update:modelValue', props.modelValue.filter((item) => item !== value))
}
</script>

<template>
  <div class="keyword-editor" :class="{ disabled }">
    <el-tag
      v-for="item in modelValue"
      :key="item"
      closable
      :disable-transitions="false"
      @close="remove(item)"
    >
      {{ item }}
    </el-tag>
    <input
      v-model="input"
      :placeholder="modelValue.length ? '继续添加' : placeholder"
      :disabled="disabled"
      @keydown.enter.prevent="add"
      @blur="add"
    />
  </div>
</template>

<style scoped>
.keyword-editor.disabled {
  opacity: 0.72;
}
</style>