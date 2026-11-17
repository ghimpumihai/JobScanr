<script lang="ts">
  interface Props {
    class?: string;
    width?: string;
    height?: string;
    rounded?: string;
  }

  let {
    class: className = '',
    width = 'w-full',
    height = 'h-4',
    rounded = 'rounded-md'
  }: Props = $props();
</script>

<div
  class="animate-pulse bg-subtle/80 {width} {height} {rounded} {className}"
  aria-hidden="true"
></div>
