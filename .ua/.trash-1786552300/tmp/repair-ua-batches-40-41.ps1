$ErrorActionPreference='Stop'
$ua=Join-Path (Get-Location) '.ua'
function Repair-Batch([int]$index){
  $paths=Get-ChildItem "$ua\intermediate\batch-$index-part-*.json" | Sort-Object Name
  $allNodes=@();$allEdges=@(); foreach($p in $paths){$x=Get-Content -Raw $p.FullName|ConvertFrom-Json;$allNodes+=@($x.nodes);$allEdges+=@($x.edges)}
  $nodeById=@{};foreach($n in $allNodes){if(!$nodeById.ContainsKey($n.id)){$nodeById[$n.id]=$n}}
  $edgeByKey=@{};foreach($e in $allEdges){$k="$($e.source)|$($e.target)|$($e.type)|$($e.direction)|$($e.weight)";if(!$edgeByKey.ContainsKey($k)){$edgeByKey[$k]=$e}}
  $fileNodes=@($nodeById.Values|Where-Object {$_.type -in @('file','config','document','service','pipeline','schema','resource','table','endpoint')}|Sort-Object filePath)
  $units=@()
  foreach($file in $fileNodes){
    $children=@($nodeById.Values|Where-Object {$_.filePath -eq $file.filePath -and $_.id -ne $file.id}|Sort-Object id)
    $chunkCount=[Math]::Max(1,[Math]::Ceiling($children.Count / 59.0))
    foreach($chunkIndex in 0..($chunkCount-1)){
      $childrenChunk=@($children | Select-Object -Skip ($chunkIndex * 59) -First 59);$ids=@{};$ids[$file.id]=$true;foreach($n in $childrenChunk){$ids[$n.id]=$true}
      $edges=New-Object System.Collections.Generic.List[object]
      foreach($e in $edgeByKey.Values){
        if($e.source -eq $file.id){
          $targetIsChild=$nodeById.ContainsKey($e.target) -and $nodeById[$e.target].filePath -eq $file.filePath -and $e.target -ne $file.id
          if(($targetIsChild -and $ids.ContainsKey($e.target)) -or (!$targetIsChild -and $chunkIndex -eq 0)){$edges.Add($e)}
        } elseif($ids.ContainsKey($e.source)) {$edges.Add($e)}
      }
      if($ids.Count -gt 60 -or $edges.Count -gt 120){throw "unit over limit batch $index $($file.filePath) part $chunkIndex nodes=$($ids.Count) edges=$($edges.Count)"}
      $unitNodes=New-Object System.Collections.Generic.List[object]; foreach($nodeId in $ids.Keys){$unitNodes.Add($nodeById[$nodeId])}
      $units += [pscustomobject]@{FileId=$file.id;Nodes=$unitNodes.ToArray();Edges=$edges.ToArray()}
    }
  }
  $script:frags=@();$script:currentNodes=@{};$script:currentEdges=New-Object System.Collections.Generic.List[object];$script:currentFileIds=@{}
  Write-Output "repair $index units=$($units.Count) sizes=$(($units|ForEach-Object {$_.Nodes.Count}) -join ',')"
  function Flush-Current {if($script:currentNodes.Count){$nArray=[object[]]$script:currentNodes.Values;$script:frags += [pscustomobject]@{Nodes=$nArray;Edges=$script:currentEdges.ToArray()}};$script:currentNodes=@{};$script:currentEdges=New-Object System.Collections.Generic.List[object];$script:currentFileIds=@{}}
  foreach($u in $units){
    if($script:currentNodes.Count){Flush-Current}
    foreach($n in $u.Nodes){$script:currentNodes[$n.id]=$n}; foreach($e in $u.Edges){$script:currentEdges.Add($e)};$script:currentFileIds[$u.FileId]=$true
  }; Flush-Current; Write-Output "repair $index fragments=$($script:frags.Count)"
  $seenNodes=@{};$seenEdges=@{};foreach($f in $script:frags){if($f.Nodes.Count -gt 60 -or $f.Edges.Count -gt 120){throw 'fragment limit failure'};foreach($n in $f.Nodes){$seenNodes[$n.id]=$true};foreach($e in $f.Edges){$k="$($e.source)|$($e.target)|$($e.type)|$($e.direction)|$($e.weight)";if($seenEdges.ContainsKey($k)){throw "duplicate edge $k"};$seenEdges[$k]=$true;if(!($f.Nodes.id -contains $e.source)){throw "missing edge source $($e.source)"}}}
  if($seenNodes.Count -ne $nodeById.Count -or $seenEdges.Count -ne $edgeByKey.Count){throw "coverage mismatch nodes $($seenNodes.Count)/$($nodeById.Count) edges $($seenEdges.Count)/$($edgeByKey.Count)"}
  $tmp=@();for($i=0;$i -lt $script:frags.Count;$i++){$out=[ordered]@{nodes=@($script:frags[$i].Nodes);edges=@($script:frags[$i].Edges)};$name="$ua\intermediate\batch-$index-part-$($i+1).json.repair";$out|ConvertTo-Json -Depth 8|Set-Content -Encoding utf8 $name;Get-Content -Raw $name|ConvertFrom-Json|Out-Null;$tmp+=$name}
  Remove-Item $paths.FullName -Force
  foreach($name in $tmp){Move-Item $name ($name -replace '\.repair$','')}
  [pscustomobject]@{Batch=$index;Parts=$script:frags.Count;UniqueNodes=$nodeById.Count;UniqueEdges=$edgeByKey.Count;Counts=($script:frags|ForEach-Object {"$($_.Nodes.Count)n/$($_.Edges.Count)e"}) -join ', '}
}
Repair-Batch 40
Repair-Batch 41
