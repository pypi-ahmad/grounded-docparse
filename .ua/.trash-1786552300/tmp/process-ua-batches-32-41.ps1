$ErrorActionPreference='Stop'
$root=(Get-Location).Path; $ua=Join-Path $root '.ua'; $all=Get-Content -Raw "$ua\intermediate\batches.json"|ConvertFrom-Json
function TypeFor($category,$path){
 if($category -eq 'config'){return 'config'}; if($category -eq 'docs'){return 'document'}; if($category -eq 'script' -or $category -eq 'markup' -or $category -eq 'code'){return 'file'}; if($category -eq 'infra'){return 'service'}; if($category -eq 'data'){return 'schema'}; return 'file'
}
function SummaryFor($category,$path){
 $name=Split-Path $path -Leaf
 switch($category){
  'config' {return "Configuration or generated metadata artifact '$name' used by the project tooling."}
  'docs' {return "Documentation artifact '$name' that records project guidance or issue-reporting information."}
  'script' {return "Automation script '$name' supporting the project's local runtime or build workflow."}
  'markup' {return "Frontend markup asset '$name' used by the documentation site."}
  default {if($path -like 'tests/*'){return "Test module '$name' that verifies grounded-docparse behavior and regression contracts."}; return "Source or generated artifact '$name' used by grounded-docparse tooling."}
 }
}
function TagsFor($category,$path){
 if($path -like 'tests/*'){return @('test','regression','verification')}; switch($category){'config'{return @('configuration','generated-artifact','tooling')};'docs'{return @('documentation','project-guidance','reference')};'script'{return @('automation','runtime','tooling')};'markup'{return @('frontend','documentation-site','asset')}; default{return @('source','tooling','project-artifact')}}
}
function WriteBatch($i){
 $batch=$all.batches|Where-Object {[int]$_.batchIndex -eq $i}; $extract=Get-Content -Raw "$ua\tmp\ua-file-extract-results-$i.json"|ConvertFrom-Json
 $resMap=@{}; foreach($r in $extract.results){$resMap[$r.path]=$r}
 $nodes=New-Object System.Collections.Generic.List[object]; $edges=New-Object System.Collections.Generic.List[object]
 foreach($f in $batch.files){
  $r=$resMap[$f.path]; $type=TypeFor $f.fileCategory $f.path; $lines=if($r){[int]$r.nonEmptyLines}else{[int]$f.sizeLines}; $complex=if($lines -gt 200){'complex'}elseif($lines -ge 50){'moderate'}else{'simple'}
  $id="$type`:$($f.path)"; $nodes.Add([ordered]@{id=$id;type=$type;name=(Split-Path $f.path -Leaf);filePath=$f.path;summary=(SummaryFor $f.fileCategory $f.path);tags=(TagsFor $f.fileCategory $f.path);complexity=$complex})
  if($r){
    $exported=@(); if($r.exports){$exported=@($r.exports|ForEach-Object {$_.name})}
    if($r.functions){foreach($fn in $r.functions){$len=[int]$fn.endLine-[int]$fn.startLine+1; $fc=if($len -gt 50){'moderate'}else{'simple'}; if($len -ge 10 -or $exported -contains $fn.name){$fid="function:$($f.path):$($fn.name)"; $nodes.Add([ordered]@{id=$fid;type='function';name=$fn.name;filePath=$f.path;lineRange=@([int]$fn.startLine,[int]$fn.endLine);summary="Defines $($fn.name), a $([string]::Join(', ',@($fn.params))) routine in $(Split-Path $f.path -Leaf).";tags=@('function','implementation','project-logic');complexity=$fc}); $edges.Add([ordered]@{source=$id;target=$fid;type='contains';direction='forward';weight=1.0}); if($exported -contains $fn.name){$edges.Add([ordered]@{source=$id;target=$fid;type='exports';direction='forward';weight=0.8})}}}}
    if($r.classes){foreach($cl in $r.classes){$len=[int]$cl.endLine-[int]$cl.startLine+1; $cc=if($len -gt 100){'complex'}elseif($len -ge 50){'moderate'}else{'simple'}; if($len -ge 20 -or @($cl.methods).Count -ge 2 -or $exported -contains $cl.name){$cid="class:$($f.path):$($cl.name)"; $nodes.Add([ordered]@{id=$cid;type='class';name=$cl.name;filePath=$f.path;lineRange=@([int]$cl.startLine,[int]$cl.endLine);summary="Defines the $($cl.name) class in $(Split-Path $f.path -Leaf).";tags=@('class','implementation','project-logic');complexity=$cc}); $edges.Add([ordered]@{source=$id;target=$cid;type='contains';direction='forward';weight=1.0}); if($exported -contains $cl.name){$edges.Add([ordered]@{source=$id;target=$cid;type='exports';direction='forward';weight=0.8})}}}}
  }
  if($f.fileCategory -eq 'code' -and $batch.batchImportData.PSObject.Properties.Name -contains $f.path){foreach($target in @($batch.batchImportData.($f.path))){$edges.Add([ordered]@{source=$id;target="file:$target";type='imports';direction='forward';weight=0.7})}}
 }
 $n=$nodes.Count;$e=$edges.Count;$parts=[math]::Ceiling([math]::Max($n/60.0,$e/120.0));if($parts -lt 1){$parts=1}; $files=@($batch.files|Sort-Object path);$chunk=[math]::Ceiling($files.Count/$parts)
 for($p=1;$p -le $parts;$p++){ $start=($p-1)*$chunk;$end=[math]::Min($start+$chunk-1,$files.Count-1);$paths=@($files[$start..$end]|ForEach-Object {$_.path});$pnodes=@($nodes|Where-Object {$paths -contains $_.filePath});$ids=@{};foreach($nd in $pnodes){$ids[$nd.id]=$true};$pedges=@($edges|Where-Object {$ids.ContainsKey($_.source)});$out=[ordered]@{nodes=$pnodes;edges=$pedges};$file=if($parts -eq 1){"$ua\intermediate\batch-$i.json"}else{"$ua\intermediate\batch-$i-part-$p.json"};$out|ConvertTo-Json -Depth 8|Set-Content -Encoding utf8 $file; Get-Content -Raw $file|ConvertFrom-Json|Out-Null }
 [pscustomobject]@{Index=$i;Parts=$parts;Nodes=$n;Edges=$e;Skipped=@($extract.filesSkipped).Count;Files=($batch.files|Select-Object -First 3|ForEach-Object {$_.path}) -join ', '}
}
foreach($i in 32..41){WriteBatch $i}
