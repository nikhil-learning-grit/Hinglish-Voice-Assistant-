param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)
python -m unittest $Args
