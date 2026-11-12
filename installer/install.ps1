<#
  Huginn's installer. "Install Huginn.bat" opens it; Settings > Apps > Huginn > Uninstall opens it with -Uninstall.

  It installs for the current user only (no admin rights): copies Huginn to a folder (by default
  %LOCALAPPDATA%\Programs\Huginn), runs setup.bat there (a portable Python and the browser engine;
  its progress is read from setup.log), adds shortcuts and an entry in Settings > Apps.
  The optional "H.264 video" switch leaves engine\build-requested.json: Huginn itself starts that
  build, in the background, the first time it opens (progress in Privacy & Security > Video).
#>
param(
    [switch]$Uninstall,
    [string]$Target = ''
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms
# The window is all there is (PowerShell's console is hidden), so anything unexpected is shown, not swallowed.
trap {
    $message = "$($_.Exception.Message)`n`n$($_.InvocationInfo.PositionMessage)"
    try { Set-Content -LiteralPath (Join-Path $env:TEMP 'huginn-installer-error.txt') -Value $message } catch { }
    [Windows.MessageBox]::Show("The installer ran into a problem:`n`n$($_.Exception.Message)", 'Huginn') | Out-Null
    exit 1
}

$Here = $PSScriptRoot
$Source = Split-Path -Parent $Here
$AppsKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Huginn'
$DefaultTarget = Join-Path $env:LOCALAPPDATA 'Programs\Huginn'
$NeedGB = 1.5            # Python and the engine, with room to unpack
$BuildGB = 60            # the H.264 build while it works (engine\build_engine.py MIN_FREE_GB)
$DataDir = Join-Path $env:LOCALAPPDATA 'SafariQt'       # bookmarks, history, profile (Huginn's first name)
$SettingsKey = 'HKCU:\Software\SafariQt'
$KeepInData = @('release-key.pem')                     # the key that signs updates you share
# Never copied from the source folder (a folder someone ran Huginn in, rather than a fresh package).
$SkipDirs = @('python', '__pycache__', 'test_out', 'standard-engine', '.git')
$SkipFiles = @('setup.log', 'installed.json', 'state.json', 'status.json', 'status.txt', 'build-log.txt',
               'builder.pid', 'update-check.json', 'restart.json', 'last-error.txt', 'build-requested.json')

# ------------------------------------------------------------------------------------------ look
function Test-LightTheme {
    try {
        $v = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name AppsUseLightTheme
        return $v.AppsUseLightTheme -eq 1
    } catch { return $true }                                  # Windows' default
}

# Huginn's Aurora realm (safari_browser.py build_theme / start_page_colours), as WPF #AARRGGBB.
if (Test-LightTheme) {
    $C = @{ bgTop = '#FFC3E3D9'; bg = '#FFEAECF6'; text = '#FF101317'; muted = '#FF464D57'; faint = '#FF8A929B'
            accent = '#FF0A8071'; accentText = '#FFFFFFFF'; card = '#E0FFFFFF'; cardLine = '#2E141E28'
            frameLine = '#3A141E28'; track = '#2A141E28'; pill = '#F2FFFFFF'; glowA = '#FF3DD6B5'; glowB = '#FF7B61FF'
            glow = '0.55'; shadow = '0.28'; danger = '#FFD13438'; warn = '#FF9A5B00'; off = '#33141E28'
            idleDot = '#33141E28' }
} else {
    $C = @{ bgTop = '#FF16201F'; bg = '#FF121519'; text = '#FFECEFF3'; muted = '#FF9AA3AD'; faint = '#FF5C646D'
            accent = '#FF43D9B8'; accentText = '#FF06241E'; card = '#0DFFFFFF'; cardLine = '#1AFFFFFF'
            frameLine = '#24FFFFFF'; track = '#1FFFFFFF'; pill = '#14FFFFFF'; glowA = '#FF3DD6B5'; glowB = '#FF7B61FF'
            glow = '0.30'; shadow = '0.55'; danger = '#FFFF6B6B'; warn = '#FFF2B35B'; off = '#38FFFFFF'
            idleDot = '#38FFFFFF' }
}

function Step-Xaml([int]$i) {
@"
<Grid Margin="0,6">
  <Grid.ColumnDefinitions><ColumnDefinition Width="28"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
  <Grid Width="16" Height="16" HorizontalAlignment="Left" VerticalAlignment="Center">
    <Ellipse x:Name="Wait$i" Stroke="@@faint@@" StrokeThickness="1.5"/>
    <Grid x:Name="Run$i" Visibility="Collapsed">
      <Ellipse Stroke="@@track@@" StrokeThickness="2"/>
      <Path Data="M8,1 A7,7 0 0 1 15,8" Stroke="@@accent@@" StrokeThickness="2" StrokeStartLineCap="Round"
            StrokeEndLineCap="Round" Width="16" Height="16" RenderTransformOrigin="0.5,0.5">
        <Path.RenderTransform><RotateTransform/></Path.RenderTransform>
        <Path.Triggers><EventTrigger RoutedEvent="FrameworkElement.Loaded"><BeginStoryboard><Storyboard RepeatBehavior="Forever">
          <DoubleAnimation Storyboard.TargetProperty="(UIElement.RenderTransform).(RotateTransform.Angle)" From="0" To="360" Duration="0:0:0.9"/>
        </Storyboard></BeginStoryboard></EventTrigger></Path.Triggers>
      </Path>
    </Grid>
    <Grid x:Name="Done$i" Visibility="Collapsed">
      <Ellipse Fill="@@accent@@"/>
      <Path Data="M4.6,8.3 L7,10.6 L11.5,5.7" Stroke="@@accentText@@" StrokeThickness="1.8" StrokeStartLineCap="Round"
            StrokeEndLineCap="Round" StrokeLineJoin="Round"/>
    </Grid>
    <Grid x:Name="Fail$i" Visibility="Collapsed">
      <Ellipse Fill="@@danger@@"/>
      <Path Data="M8,4.3 L8,9 M8,11.5 L8,11.6" Stroke="#FFFFFFFF" StrokeThickness="1.8" StrokeStartLineCap="Round" StrokeEndLineCap="Round"/>
    </Grid>
  </Grid>
  <TextBlock x:Name="StepText$i" Grid.Column="1" VerticalAlignment="Center"/>
  <TextBlock x:Name="StepInfo$i" Grid.Column="2" VerticalAlignment="Center" Foreground="@@muted@@" FontSize="12" Margin="12,0,0,0"/>
</Grid>
"@
}

$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Install Huginn" Width="600" Height="680" WindowStyle="None" AllowsTransparency="True"
        Background="Transparent" ResizeMode="CanMinimize" WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI Variable Text, Segoe UI" FontSize="13" Foreground="@@text@@"
        UseLayoutRounding="True" SnapsToDevicePixels="True" TextOptions.TextFormattingMode="Ideal">
  <Window.Resources>
    <SolidColorBrush x:Key="Muted" Color="@@muted@@"/>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="CornerRadius" Value="12"/>
      <Setter Property="Background" Value="@@card@@"/>
      <Setter Property="BorderBrush" Value="@@cardLine@@"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="16,11"/>
      <Setter Property="Margin" Value="0,0,0,8"/>
    </Style>
    <Style x:Key="Title" TargetType="TextBlock">
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="@@muted@@"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
      <Setter Property="Margin" Value="0,2,0,0"/>
    </Style>
    <Style x:Key="Pill" TargetType="Button">
      <Setter Property="Foreground" Value="@@text@@"/>
      <Setter Property="Background" Value="@@pill@@"/>
      <Setter Property="BorderBrush" Value="@@cardLine@@"/>
      <Setter Property="Padding" Value="20,7"/>
      <Setter Property="MinWidth" Value="96"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" CornerRadius="16" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Opacity" Value="0.86"/></Trigger>
              <Trigger Property="IsPressed" Value="True"><Setter TargetName="b" Property="Opacity" Value="0.72"/></Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter TargetName="b" Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource Pill}">
      <Setter Property="Background" Value="@@accent@@"/>
      <Setter Property="BorderBrush" Value="@@accent@@"/>
      <Setter Property="Foreground" Value="@@accentText@@"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Danger" TargetType="Button" BasedOn="{StaticResource Primary}">
      <Setter Property="Background" Value="@@danger@@"/>
      <Setter Property="BorderBrush" Value="@@danger@@"/>
      <Setter Property="Foreground" Value="#FFFFFFFF"/>
    </Style>
    <Style x:Key="Link" TargetType="Button">
      <Setter Property="Foreground" Value="@@accent@@"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="Transparent" Padding="8,4">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Opacity" Value="0.75"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Switch" TargetType="ToggleButton">
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Grid Width="36" Height="20" Background="Transparent">
              <Border x:Name="track" CornerRadius="10" Background="@@off@@"/>
              <Ellipse x:Name="knob" Width="16" Height="16" Fill="#FFFFFFFF" HorizontalAlignment="Left" Margin="2,0,0,0">
                <Ellipse.RenderTransform><TranslateTransform X="0"/></Ellipse.RenderTransform>
                <Ellipse.Effect><DropShadowEffect BlurRadius="3" ShadowDepth="1" Direction="270" Opacity="0.25"/></Ellipse.Effect>
              </Ellipse>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="track" Property="Background" Value="@@accent@@"/>
                <Trigger.EnterActions><BeginStoryboard><Storyboard>
                  <DoubleAnimation Storyboard.TargetName="knob" Storyboard.TargetProperty="(UIElement.RenderTransform).(TranslateTransform.X)" To="16" Duration="0:0:0.15"/>
                </Storyboard></BeginStoryboard></Trigger.EnterActions>
                <Trigger.ExitActions><BeginStoryboard><Storyboard>
                  <DoubleAnimation Storyboard.TargetName="knob" Storyboard.TargetProperty="(UIElement.RenderTransform).(TranslateTransform.X)" To="0" Duration="0:0:0.15"/>
                </Storyboard></BeginStoryboard></Trigger.ExitActions>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Dot" TargetType="Button">
      <Setter Property="Width" Value="12"/>
      <Setter Property="Height" Value="12"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
      <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Grid>
              <Ellipse Fill="{TemplateBinding Background}" Stroke="#1F000000" StrokeThickness="0.5"/>
              <ContentPresenter x:Name="glyph" HorizontalAlignment="Center" VerticalAlignment="Center" Opacity="0"/>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="glyph" Property="Opacity" Value="1"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="20">
    <Border CornerRadius="16" Background="@@bg@@">
      <Border.Effect><DropShadowEffect BlurRadius="26" ShadowDepth="6" Direction="270" Opacity="@@shadow@@" Color="#FF000000"/></Border.Effect>
    </Border>
    <Border CornerRadius="16" BorderBrush="@@frameLine@@" BorderThickness="1">
      <Border.Background>
        <LinearGradientBrush StartPoint="0,0" EndPoint="0,1">
          <GradientStop Color="@@bgTop@@" Offset="0"/>
          <GradientStop Color="@@bg@@" Offset="0.62"/>
        </LinearGradientBrush>
      </Border.Background>
      <Grid>
        <Grid.Clip><RectangleGeometry Rect="0,0,558,638" RadiusX="15" RadiusY="15"/></Grid.Clip>
        <Canvas IsHitTestVisible="False">
          <Ellipse Width="400" Height="220" Canvas.Left="-70" Canvas.Top="-120" Fill="@@glowA@@" Opacity="@@glow@@">
            <Ellipse.Effect><BlurEffect Radius="90" KernelType="Gaussian"/></Ellipse.Effect>
          </Ellipse>
          <Ellipse Width="380" Height="210" Canvas.Left="250" Canvas.Top="-110" Fill="@@glowB@@" Opacity="@@glow@@">
            <Ellipse.Effect><BlurEffect Radius="90" KernelType="Gaussian"/></Ellipse.Effect>
          </Ellipse>
        </Canvas>

        <Grid>
          <Grid.RowDefinitions><RowDefinition Height="40"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
          <StackPanel Orientation="Horizontal" Margin="16,0,0,0" VerticalAlignment="Center">
            <Button x:Name="CloseDot" Style="{StaticResource Dot}" Background="#FFFF5F57" ToolTip="Close">
              <Path Data="M0,0 L5,5 M5,0 L0,5" Stroke="#FF8C1A10" StrokeThickness="1.2" StrokeStartLineCap="Round" StrokeEndLineCap="Round"/>
            </Button>
            <Button x:Name="MinDot" Style="{StaticResource Dot}" Background="#FFFEBC2E" ToolTip="Minimize">
              <Path Data="M0,0 L6,0" Stroke="#FF8F5A00" StrokeThickness="1.2" StrokeStartLineCap="Round" StrokeEndLineCap="Round"/>
            </Button>
            <Button Style="{StaticResource Dot}" Background="@@idleDot@@" IsHitTestVisible="False"/>
          </StackPanel>

          <StackPanel Grid.Row="1" HorizontalAlignment="Center" Margin="40,2,40,0">
            <Image x:Name="Logo" Width="64" Height="64" HorizontalAlignment="Center" RenderOptions.BitmapScalingMode="HighQuality">
              <Image.Effect><DropShadowEffect BlurRadius="14" ShadowDepth="3" Direction="270" Opacity="0.3"/></Image.Effect>
            </Image>
            <TextBlock Text="ᚺ ᚢ ᚷ ᛁ ᚾ ᚾ" FontFamily="Segoe UI Historic, Segoe UI Symbol" FontSize="11"
                       Foreground="@@accent@@" Opacity="0.75" HorizontalAlignment="Center" Margin="0,10,0,0"/>
            <TextBlock x:Name="Heading" Text="Install Huginn" FontFamily="Segoe UI Variable Display, Segoe UI"
                       FontWeight="Light" FontSize="28" HorizontalAlignment="Center" Margin="0,2,0,0"/>
            <TextBlock x:Name="Lead" Style="{StaticResource Sub}" FontSize="13" TextAlignment="Center" MaxWidth="400"
                       HorizontalAlignment="Center" Margin="0,4,0,0"/>
          </StackPanel>

          <Grid Grid.Row="2" Margin="40,18,40,22">
            <!-- options -->
            <Grid x:Name="PageOptions">
              <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
              <StackPanel>
                <Border Style="{StaticResource Card}">
                  <Grid>
                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                    <StackPanel>
                      <TextBlock Style="{StaticResource Title}" Text="Install to"/>
                      <TextBlock x:Name="PathText" Style="{StaticResource Sub}" TextWrapping="NoWrap" TextTrimming="CharacterEllipsis"/>
                    </StackPanel>
                    <Button x:Name="ChangeButton" Grid.Column="1" Style="{StaticResource Link}" Content="Change…" Margin="10,0,-8,0"/>
                  </Grid>
                </Border>
                <Border Style="{StaticResource Card}">
                  <Grid>
                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                    <StackPanel>
                      <TextBlock Style="{StaticResource Title}" Text="Desktop shortcut"/>
                      <TextBlock Style="{StaticResource Sub}" Text="Huginn's raven on your desktop"/>
                    </StackPanel>
                    <ToggleButton x:Name="DesktopSwitch" Grid.Column="1" Style="{StaticResource Switch}" IsChecked="True" Margin="12,0,0,0"/>
                  </Grid>
                </Border>
                <Border Style="{StaticResource Card}">
                  <Grid>
                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                    <StackPanel>
                      <TextBlock Style="{StaticResource Title}" Text="Start menu and taskbar"/>
                      <TextBlock Style="{StaticResource Sub}"
                                 Text="Huginn is always in Start. To keep it on the taskbar, right-click its icon there once it's open and choose Pin to taskbar."/>
                    </StackPanel>
                    <TextBlock Grid.Column="1" Style="{StaticResource Sub}" Text="Always" VerticalAlignment="Center" Margin="12,0,2,0"/>
                  </Grid>
                </Border>
                <Border Style="{StaticResource Card}">
                  <Grid>
                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                    <StackPanel>
                      <TextBlock Style="{StaticResource Title}" Text="Build H.264 video support"/>
                      <TextBlock x:Name="VideoText" Style="{StaticResource Sub}"/>
                    </StackPanel>
                    <ToggleButton x:Name="VideoSwitch" Grid.Column="1" Style="{StaticResource Switch}" IsChecked="False" Margin="12,0,0,0"/>
                  </Grid>
                </Border>
                <TextBlock x:Name="NoteText" Style="{StaticResource Sub}" TextAlignment="Center" Margin="0,6,0,0"/>
              </StackPanel>
              <StackPanel Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right">
                <Button x:Name="CancelButton" Style="{StaticResource Pill}" Content="Cancel" IsCancel="True"/>
                <Button x:Name="InstallButton" Style="{StaticResource Primary}" Content="Install" IsDefault="True"/>
              </StackPanel>
            </Grid>

            <!-- progress (install and remove) -->
            <Grid x:Name="PageProgress" Visibility="Collapsed">
              <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
              <StackPanel>
                <Border Style="{StaticResource Card}" Padding="18,12">
                  <StackPanel>
                    @@steps@@
                  </StackPanel>
                </Border>
                <Grid Height="4" Margin="2,10,2,0">
                  <Border CornerRadius="2" Background="@@track@@"/>
                  <Border x:Name="Bar" CornerRadius="2" Background="@@accent@@" HorizontalAlignment="Left" Width="0"/>
                </Grid>
                <TextBlock x:Name="DetailText" Style="{StaticResource Sub}" TextWrapping="NoWrap" TextTrimming="CharacterEllipsis" Margin="2,10,2,0"/>
              </StackPanel>
              <StackPanel Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right">
                <Button x:Name="StopButton" Style="{StaticResource Pill}" Content="Cancel"/>
              </StackPanel>
            </Grid>

            <!-- done -->
            <Grid x:Name="PageDone" Visibility="Collapsed">
              <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
              <Border Style="{StaticResource Card}" VerticalAlignment="Top" Padding="18,14">
                <StackPanel x:Name="DoneList"/>
              </Border>
              <StackPanel Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right">
                <Button x:Name="CloseButton" Style="{StaticResource Pill}" Content="Close"/>
                <Button x:Name="OpenButton" Style="{StaticResource Primary}" Content="Open Huginn" IsDefault="True"/>
              </StackPanel>
            </Grid>

            <!-- failed -->
            <Grid x:Name="PageFailed" Visibility="Collapsed">
              <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
              <Border Style="{StaticResource Card}" VerticalAlignment="Top" Padding="18,14">
                <StackPanel>
                  <TextBlock Style="{StaticResource Title}" Text="Setup didn't finish" Foreground="@@danger@@"/>
                  <TextBlock x:Name="FailText" Style="{StaticResource Sub}" FontSize="13" Margin="0,6,0,0"/>
                  <TextBlock Style="{StaticResource Sub}" Margin="0,10,0,0"
                             Text="Try again carries on where it stopped. Nothing outside the install folder was changed."/>
                </StackPanel>
              </Border>
              <StackPanel Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right">
                <Button x:Name="LogButton" Style="{StaticResource Link}" Content="Show log" Margin="0,0,8,0"/>
                <Button x:Name="FailCloseButton" Style="{StaticResource Pill}" Content="Close"/>
                <Button x:Name="RetryButton" Style="{StaticResource Primary}" Content="Try again" IsDefault="True"/>
              </StackPanel>
            </Grid>

            <!-- remove -->
            <Grid x:Name="PageRemove" Visibility="Collapsed">
              <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
              <StackPanel>
                <Border Style="{StaticResource Card}">
                  <StackPanel>
                    <TextBlock Style="{StaticResource Title}" Text="Installed in"/>
                    <TextBlock x:Name="RemovePath" Style="{StaticResource Sub}" TextWrapping="NoWrap" TextTrimming="CharacterEllipsis"/>
                  </StackPanel>
                </Border>
                <Border Style="{StaticResource Card}">
                  <Grid>
                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                    <StackPanel>
                      <TextBlock Style="{StaticResource Title}" Text="Also remove my bookmarks, history and passwords"/>
                      <TextBlock Style="{StaticResource Sub}"
                                 Text="And your settings. Every copy of Huginn on this PC shares them, so leave this off to keep them for later."/>
                    </StackPanel>
                    <ToggleButton x:Name="DataSwitch" Grid.Column="1" Style="{StaticResource Switch}" IsChecked="False" Margin="12,0,0,0"/>
                  </Grid>
                </Border>
              </StackPanel>
              <StackPanel Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right">
                <Button x:Name="KeepButton" Style="{StaticResource Pill}" Content="Cancel" IsCancel="True"/>
                <Button x:Name="RemoveButton" Style="{StaticResource Danger}" Content="Remove"/>
              </StackPanel>
            </Grid>
          </Grid>
        </Grid>
      </Grid>
    </Border>
  </Grid>
</Window>
'@

$steps = (1..5 | ForEach-Object { Step-Xaml $_ }) -join "`n"
$Xaml = $Xaml.Replace('@@steps@@', $steps)
foreach ($k in $C.Keys) { $Xaml = $Xaml.Replace("@@$k@@", $C[$k]) }

# ------------------------------------------------------------------------------------------ window
$window = [Windows.Markup.XamlReader]::Parse($Xaml)
$ui = @{}
foreach ($name in 'CloseDot', 'MinDot', 'Logo', 'Heading', 'Lead', 'PageOptions', 'PathText', 'ChangeButton',
                  'DesktopSwitch', 'VideoText', 'VideoSwitch', 'NoteText', 'CancelButton', 'InstallButton',
                  'PageProgress', 'Bar', 'DetailText', 'StopButton', 'PageDone', 'DoneList', 'CloseButton', 'OpenButton',
                  'PageFailed', 'FailText', 'LogButton', 'FailCloseButton', 'RetryButton', 'PageRemove', 'RemovePath',
                  'DataSwitch', 'KeepButton', 'RemoveButton') {
    $ui[$name] = $window.FindName($name)
}
foreach ($i in 1..5) {
    foreach ($part in 'Wait', 'Run', 'Done', 'Fail', 'StepText', 'StepInfo') { $ui["$part$i"] = $window.FindName("$part$i") }
}

$S = @{ target = ''; proc = $null; phase = ''; logPos = 0; partial = ''; files = @{}; current = ''; fraction = 0.0
        closing = @(); closeSince = $null; removing = $false; video = $false; links = @(); failed = $false
        stopped = $false; update = $false; lastError = $null }

function Brush([string]$hex) { New-Object Windows.Media.SolidColorBrush ([Windows.Media.ColorConverter]::ConvertFromString($hex)) }

function Get-Logo([string]$ico) {
    if (-not (Test-Path -LiteralPath $ico)) { return $null }
    try {
        $decoder = [Windows.Media.Imaging.BitmapDecoder]::Create((New-Object Uri $ico),
            [Windows.Media.Imaging.BitmapCreateOptions]::None, [Windows.Media.Imaging.BitmapCacheOption]::OnLoad)
        return $decoder.Frames | Sort-Object { $_.PixelWidth } | Select-Object -Last 1
    } catch { return $null }
}

function Show-Page([string]$name) {
    foreach ($page in 'PageOptions', 'PageProgress', 'PageDone', 'PageFailed', 'PageRemove') {
        $ui[$page].Visibility = if ($page -eq $name) { 'Visible' } else { 'Collapsed' }
    }
    $window.UpdateLayout()
    $fade = New-Object Windows.Media.Animation.DoubleAnimation ([double]0), ([double]1),
        (New-Object Windows.Duration ([TimeSpan]::FromMilliseconds(220)))
    $ui[$name].BeginAnimation([Windows.UIElement]::OpacityProperty, $fade)
}

function Set-Step([int]$i, [string]$state, [string]$info = $null) {
    foreach ($part in 'Wait', 'Run', 'Done', 'Fail') {
        $ui["$part$i"].Visibility = if ($part -eq $state) { 'Visible' } else { 'Collapsed' }
    }
    $ui["StepText$i"].Opacity = if ($state -eq 'Wait') { 0.55 } else { 1.0 }
    if ($null -ne $info) { $ui["StepInfo$i"].Text = $info }
}

function Set-Progress([double]$fraction) {
    $fraction = [Math]::Max(0.0, [Math]::Min(1.0, $fraction))
    if ($fraction -lt $S.fraction) { return }                   # never goes backwards
    $S.fraction = $fraction
    $track = $ui.Bar.Parent.ActualWidth
    if ($track -le 0) { $track = 474 }                          # before the first layout pass
    $grow = New-Object Windows.Media.Animation.DoubleAnimation ([double]($track * $fraction)),
        (New-Object Windows.Duration ([TimeSpan]::FromMilliseconds(300)))
    $ui.Bar.BeginAnimation([Windows.FrameworkElement]::WidthProperty, $grow)
}

function Set-Detail([string]$text) { $ui.DetailText.Text = $text }

function Add-DoneLine([string]$text, [bool]$accent = $false) {
    $line = New-Object Windows.Controls.TextBlock
    $line.Text = $text
    $line.TextWrapping = 'Wrap'
    $line.Margin = '0,0,0,8'
    if ($accent) { $line.Foreground = Brush $C.accent } else { $line.Foreground = Brush $C.text }
    [void]$ui.DoneList.Children.Add($line)
}

# ------------------------------------------------------------------------------------------ checks
function Get-FreeGB([string]$path) {
    try {
        $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path))
        return (New-Object IO.DriveInfo $root).AvailableFreeSpace / 1GB
    } catch { return -1 }
}

function Get-BuildDrive {
    # The builder prefers the system drive, else the fixed drive with the most room (choose_work_dir).
    $best = $null
    foreach ($d in [IO.DriveInfo]::GetDrives()) {
        if ($d.DriveType -ne 'Fixed' -or -not $d.IsReady) { continue }
        $gb = $d.AvailableFreeSpace / 1GB
        if ($null -eq $best -or $gb -gt $best.gb) { $best = @{ name = $d.Name.TrimEnd('\'); gb = $gb } }
    }
    return $best
}

function Get-BuildHours {
    # Same estimate as safari_browser.py build_hours_estimate().
    $cpus = [Environment]::ProcessorCount
    try { $ram = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB } catch { $ram = 8 }
    $jobs = [Math]::Max(1, [Math]::Min($cpus, [Math]::Floor(($ram - 2) / 2.5)))
    $hours = 22 / $jobs + 0.5
    return @([Math]::Max(1, [Math]::Round($hours * 0.75)), [Math]::Max(2, [Math]::Round($hours * 1.4)))
}

function Test-Inside([string]$child, [string]$parent) {
    $c = [IO.Path]::GetFullPath($child).TrimEnd('\') + '\'
    $p = [IO.Path]::GetFullPath($parent).TrimEnd('\') + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

function Test-Same([string]$a, [string]$b) {
    return [IO.Path]::GetFullPath($a).TrimEnd('\') -ieq [IO.Path]::GetFullPath($b).TrimEnd('\')
}

function Set-Target([string]$path) {
    $S.target = [IO.Path]::GetFullPath($path)
    $ui.PathText.Text = $S.target
    $ui.PathText.ToolTip = $S.target
    Update-Note
}

function Show-Warning([string]$text) {
    if ($ui.PageOptions.Visibility -ne 'Visible') { Show-Page 'PageOptions' }
    $ui.NoteText.Text = $text
    $ui.NoteText.Foreground = Brush $C.warn
}

function Update-Note {
    $free = Get-FreeGB $S.target
    $ui.NoteText.Foreground = Brush $C.muted
    if ($free -ge 0 -and $free -lt $NeedGB) {
        $ui.NoteText.Text = ('Huginn needs about {0} GB free there; that drive has {1:0.0} GB.' -f $NeedGB, $free)
        $ui.NoteText.Foreground = Brush $C.warn
        $ui.InstallButton.IsEnabled = $false
        return
    }
    $ui.InstallButton.IsEnabled = $true
    $ui.NoteText.Text = 'For you only, no admin rights needed  ·  about 1 GB  ·  remove it any time from Settings › Apps'
}

# ------------------------------------------------------------------------------------------ install
function Copy-Huginn([string]$from, [string]$to) {
    New-Item -ItemType Directory -Path $to -Force | Out-Null
    if (Test-Same $from $to) { return }                         # run from the install folder: nothing to copy
    $fromFull = [IO.Path]::GetFullPath($from).TrimEnd('\')
    foreach ($file in (Get-ChildItem -LiteralPath $fromFull -Recurse -File -Force)) {
        $rel = $file.FullName.Substring($fromFull.Length + 1)
        $folders = @($rel.Split('\') | Select-Object -SkipLast 1)
        if (@($folders | Where-Object { $SkipDirs -contains $_ }).Count -gt 0) { continue }
        if ($SkipFiles -contains $file.Name -or $file.Extension -eq '.log') { continue }
        $dest = Join-Path $to $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
        Unblock-File -LiteralPath $dest -ErrorAction SilentlyContinue   # installed files aren't "from the internet" any more
    }
}

function Write-AppsEntry([string]$folder) {
    $version = '1.0'
    $versionFile = Join-Path $folder 'version.txt'
    if (Test-Path -LiteralPath $versionFile) { $version = (Get-Content -LiteralPath $versionFile -TotalCount 1).Trim() }
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $script = Join-Path $folder 'installer\install.ps1'
    New-Item -Path $AppsKey -Force | Out-Null
    $values = @{
        DisplayName = 'Huginn'; DisplayVersion = $version; Publisher = 'Huginn'
        DisplayIcon = (Join-Path $folder 'Huginn.ico'); InstallLocation = $folder
        UninstallString = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File `"$script`" -Uninstall"
        InstallDate = (Get-Date -Format 'yyyyMMdd')
    }
    foreach ($k in $values.Keys) { Set-ItemProperty -Path $AppsKey -Name $k -Value $values[$k] }
    foreach ($k in 'NoModify', 'NoRepair') { New-ItemProperty -Path $AppsKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
}

function Set-AppsSize([string]$folder) {
    try {
        $kb = [int]((Get-ChildItem -LiteralPath $folder -Recurse -File -Force -ErrorAction SilentlyContinue |
                     Measure-Object Length -Sum).Sum / 1KB)
        New-ItemProperty -Path $AppsKey -Name EstimatedSize -Value $kb -PropertyType DWord -Force | Out-Null
    } catch { }
}

function Start-Hidden([string]$file, [string]$arguments, [string]$folder) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $file
    $info.Arguments = $arguments
    $info.WorkingDirectory = $folder
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    return [Diagnostics.Process]::Start($info)
}

function Protect-Folder([string]$folder) {
    # A folder made outside your own profile (C:\Huginn, another drive) can by default be changed
    # by every account on this PC, and Huginn runs from it. Only you, administrators and Windows
    # itself may write there; the folder's inherited permissions go only once those are in place.
    try {
        $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $path = '"' + $folder.TrimEnd('\') + '"'
        $grant = Start-Hidden 'icacls.exe' "$path /grant:r *${me}:(OI)(CI)F *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F" $env:TEMP
        $grant.WaitForExit()
        if ($grant.ExitCode -ne 0) { return }
        (Start-Hidden 'icacls.exe' "$path /inheritance:r" $env:TEMP).WaitForExit()
    } catch { }
}

function Stop-Tree($proc) {
    if ($null -eq $proc -or $proc.HasExited) { return }
    Start-Hidden 'taskkill.exe' "/PID $($proc.Id) /T /F" $env:TEMP | Out-Null
}

function Start-Install {
    $target = $S.target
    if ((Test-Inside $target $Source) -and -not (Test-Same $target $Source)) {
        Show-Warning 'Choose a folder outside the one you unzipped.'
        return
    }
    if (@(Get-HuginnProcesses $target).Count -gt 0) {
        Show-Warning 'Huginn is open from that folder. Close it first, then press the button again.'
        return
    }
    $ours = (-not (Test-Path -LiteralPath $target)) -or (Test-Path -LiteralPath (Join-Path $target 'safari_browser.py'))
    try {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        $probe = Join-Path $target '.huginn-write-test'
        Set-Content -LiteralPath $probe -Value 'ok'
        Remove-Item -LiteralPath $probe -Force
    } catch {
        Show-Warning "Huginn can't write there. Pick a folder of your own (not Program Files)."
        return
    }
    # Huginn's own folder (new, or an earlier install), somewhere other accounts could write.
    if ($ours -and -not (Test-Inside $target $env:USERPROFILE)) { Protect-Folder $target }
    $S.video = [bool]$ui.VideoSwitch.IsChecked
    # Like Chrome and Firefox: always in the Start menu; on the desktop unless you said no.
    $S.links = @(Join-Path ([Environment]::GetFolderPath('Programs')) 'Huginn.lnk')
    if ($ui.DesktopSwitch.IsChecked) { $S.links += Join-Path ([Environment]::GetFolderPath('Desktop')) 'Huginn.lnk' }

    $ui.Heading.Text = 'Installing Huginn'
    $ui.Lead.Text = 'You can keep working; this takes a few minutes.'
    $ui.StepText1.Text = 'Copying Huginn'
    $ui.StepText2.Text = 'Getting Python'
    $ui.StepText3.Text = 'Getting the browser engine'
    $ui.StepText4.Text = 'Adding Huginn to Start'
    $ui.StepText5.Text = 'H.264 video support'
    foreach ($i in 1..5) { Set-Step $i 'Wait' '' }
    if (-not $S.video) { Set-Step 5 'Wait' 'not chosen' }
    $S.fraction = 0.0
    $ui.Bar.BeginAnimation([Windows.FrameworkElement]::WidthProperty, $null)
    $ui.Bar.Width = 0
    $ui.StopButton.IsEnabled = $true
    Show-Page 'PageProgress'
    Set-Step 1 'Run'
    Set-Detail $target
    # Let the page draw before the (short) copy.
    $window.Dispatcher.Invoke([Action]{ }, [Windows.Threading.DispatcherPriority]::Background)
    try {
        Copy-Huginn $Source $target
        Write-AppsEntry $target
        $request = Join-Path $target 'engine\build-requested.json'
        if ($S.video) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $request) -Force | Out-Null
            Set-Content -LiteralPath $request -Value ('{"requested": "' + (Get-Date -Format s) + '"}') -Encoding ASCII
        } elseif (Test-Path -LiteralPath $request) {
            Remove-Item -LiteralPath $request -Force
        }
    } catch {
        Fail-Install 1 "Copying failed: $($_.Exception.Message)"
        return
    }
    Set-Step 1 'Done' ''
    Set-Progress 0.03
    Set-Step 2 'Run'
    Set-Detail 'Checking for Python'
    $S.logPos = 0
    $S.partial = ''
    $S.lastError = $null
    $S.files = @{}
    $S.current = ''
    $S.phase = 'setup'
    $S.proc = Start-Hidden 'cmd.exe' ('/d /c ""' + (Join-Path $target 'setup.bat') + '""') $target
    $timer.Start()
}

function Read-NewLines {
    $path = Join-Path $S.target 'setup.log'
    if (-not (Test-Path -LiteralPath $path)) { return @() }
    $stream = [IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
    try {
        if ($stream.Length -lt $S.logPos) { $S.logPos = 0; $S.partial = '' }
        [void]$stream.Seek($S.logPos, 'Begin')
        $buffer = New-Object byte[] ($stream.Length - $S.logPos)
        $read = $stream.Read($buffer, 0, $buffer.Length)
        $S.logPos += $read
    } finally { $stream.Dispose() }
    $text = $S.partial + [Text.Encoding]::UTF8.GetString($buffer, 0, $read)
    $lines = $text -split "`r?`n"
    $S.partial = $lines[-1]
    if ($lines.Count -le 1) { return @() }
    return $lines[0..($lines.Count - 2)]
}

function Format-MB([double]$bytes) { return ('{0:0}' -f ($bytes / 1MB)) }

function Update-Download {
    $done = 0.0; $total = 0.0
    foreach ($f in $S.files.Values) { $done += $f.got; $total += $f.size }
    $expected = [Math]::Max($total, 240MB)                     # PySide6 + its add-ons, before pip says
    Set-Step 3 'Run' ('{0} of ~{1} MB' -f (Format-MB $done), (Format-MB $expected))
    Set-Progress (0.12 + 0.68 * ($done / $expected))
}

function Read-Setup {
    foreach ($line in (Read-NewLines)) {
        $line = $line.Trim()
        if ($line -eq 'STEP python') { Set-Step 2 'Run' ''; Set-Detail 'Downloading Python from python.org'; Set-Progress 0.04 }
        elseif ($line -eq 'STEP pip') { Set-Detail 'Adding pip, Python''s installer'; Set-Progress 0.08 }
        elseif ($line -eq 'STEP engine') {
            Set-Step 2 'Done' ''
            Set-Step 3 'Run' ''
            Set-Detail 'Asking for PySide6 (Qt WebEngine) and the password library'
            Set-Progress 0.12
        }
        elseif ($line -notlike '*.metadata*' -and $line -match '^Downloading (\S+?)-\d\S*\s+\(([\d.]+)\s*(kB|MB|GB)\)') {
            $unit = @{ kB = 1KB; MB = 1MB; GB = 1GB }[$Matches[3]]
            $S.current = $Matches[1]
            $S.files[$S.current] = @{ size = [double]$Matches[2] * $unit; got = 0.0 }
            $pretty = @{ pyside6_addons = 'PySide6 Add-ons'; pyside6_essentials = 'PySide6 Essentials'; pyside6 = 'PySide6'
                         shiboken6 = 'Shiboken6'; cryptography = 'the password library' }
            $label = if ($pretty.ContainsKey($S.current.ToLower())) { $pretty[$S.current.ToLower()] } else { $S.current -replace '_', ' ' }
            Set-Detail ('Downloading {0}  ·  {1} {2}' -f $label, $Matches[2], $Matches[3])
            Update-Download
        }
        elseif ($line -match '^Progress (\d+) of (\d+)') {
            if ($S.current -and $S.files.ContainsKey($S.current)) {
                $S.files[$S.current].got = [double]$Matches[1]
                $S.files[$S.current].size = [double]$Matches[2]
                Update-Download
            }
        }
        elseif ($line -like 'Installing collected packages*') { Set-Detail 'Unpacking the engine (about a minute)'; Set-Progress 0.82 }
        elseif ($line -like 'Successfully installed*') { Set-Progress 0.9 }
        elseif ($line -eq 'STEP check') { Set-Detail 'Checking the engine starts'; Set-Progress 0.92 }
        elseif ($line -eq 'SETUP_OK') { Set-Step 3 'Done' ''; Set-Progress 0.93 }
        elseif ($line -like 'ERROR:*' -or $line -like 'curl:*') { $S.lastError = $line }
    }
}

function Last-ErrorLine {
    $path = Join-Path $S.target 'setup.log'
    $hint = ''
    if ($S.lastError) { $hint = $S.lastError }
    if (-not $hint -and (Test-Path -LiteralPath $path)) {
        $hint = (Get-Content -LiteralPath $path -Tail 30 |
                 Where-Object { $_ -match 'error|failed|could not|denied' -and $_ -notmatch 'SETUP_FAILED' } |
                 Select-Object -Last 1)
    }
    if ($hint -match 'resolve|connect|timed out|SSL|network|curl') {
        return "Couldn't download what Huginn needs. Check the internet connection, then try again."
    }
    if ($hint) { return $hint.Trim() }
    return 'Something went wrong while setting up. The log has the details.'
}

function Start-Shortcuts {
    $S.phase = 'shortcuts'
    if ($S.links.Count -eq 0) { Finish-Install; return }
    Set-Step 4 'Run' ''
    Set-Detail $(if ($S.links.Count -gt 1) { 'Adding Huginn to Start and your desktop' } else { 'Adding Huginn to Start' })
    $python = Join-Path $S.target 'python\python.exe'
    $quoted = ($S.links | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $S.proc = Start-Hidden $python ('"' + (Join-Path $S.target 'safari_browser.py') + '" --install-shortcuts ' + $quoted) $S.target
}

function Add-PlainShortcuts {
    # Fallback when Huginn couldn't make them itself (they then lack its taskbar identity).
    $shell = New-Object -ComObject WScript.Shell
    foreach ($link in $S.links) {
        $lnk = $shell.CreateShortcut($link)
        $lnk.TargetPath = Join-Path $S.target 'python\pythonw.exe'
        $lnk.Arguments = '"' + (Join-Path $S.target 'safari_browser.py') + '"'
        $lnk.WorkingDirectory = $S.target
        $lnk.IconLocation = (Join-Path $S.target 'Huginn.ico') + ',0'
        $lnk.Description = 'Huginn - a private web browser'
        $lnk.Save()
    }
}

function Finish-Install {
    $timer.Stop()
    $S.phase = ''
    if ($S.links.Count -gt 0) { Set-Step 4 'Done' '' }
    if ($S.video) { Set-Step 5 'Done' 'starts when Huginn opens' }
    Set-Progress 1.0
    Set-AppsSize $S.target
    $ui.Heading.Text = 'Huginn is ready'
    $ui.Lead.Text = 'A quiet, private browser, set up and waiting.'
    $ui.DoneList.Children.Clear()
    $desktop = @($S.links | Where-Object { $_ -like '*Desktop*' }).Count -gt 0
    if ($desktop) { Add-DoneLine 'Huginn is in your Start menu and on your desktop.' }
    else { Add-DoneLine 'Huginn is in your Start menu: press Start and type Huginn.' }
    Add-DoneLine 'To keep it on your taskbar: open it, right-click its icon on the taskbar and choose Pin to taskbar.' $true
    if (-not $S.update) { Add-DoneLine 'A short tour shows you around the first time it opens.' }
    if ($S.video) {
        Add-DoneLine ('H.264 video support starts building when Huginn opens. It runs in the background for a few ' +
                      'hours; progress is in Privacy & Security › Video.') $true
    }
    if (-not (Test-Same $Source $S.target)) { Add-DoneLine 'The folder you unzipped isn''t needed any more.' }
    Add-DoneLine 'To remove Huginn later: Settings › Apps › Installed apps › Huginn.'
    Show-Page 'PageDone'
}

function Fail-Install([int]$step, [string]$why) {
    $timer.Stop()
    $S.phase = ''
    $S.failed = $true
    Set-Step $step 'Fail'
    $ui.Heading.Text = 'Not quite'
    $ui.Lead.Text = 'Huginn isn''t set up yet.'
    $ui.FailText.Text = $why
    Show-Page 'PageFailed'
}

function Tick-Install {
    if ($S.phase -eq 'setup') {
        Read-Setup
        if ($S.proc.HasExited) {
            Read-Setup
            $log = Join-Path $S.target 'setup.log'
            $ok = (Test-Path -LiteralPath $log) -and (Select-String -LiteralPath $log -SimpleMatch 'SETUP_OK' -Quiet)
            if ($ok) {
                Set-Step 2 'Done' ''
                Set-Step 3 'Done' ''
                Start-Shortcuts
            } else {
                $step = if ($ui.Run2.Visibility -eq 'Visible') { 2 } else { 3 }
                Fail-Install $step (Last-ErrorLine)
            }
        }
    } elseif ($S.phase -eq 'shortcuts') {
        if ($S.proc.HasExited) {
            if ($S.proc.ExitCode -ne 0) { try { Add-PlainShortcuts } catch { } }
            Finish-Install
        }
    }
}

# ------------------------------------------------------------------------------------------ remove
function Get-HuginnProcesses([string]$folder) {
    $prefix = $folder.TrimEnd('\') + '\'
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
            $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
        })
    } catch { return @() }
}

function Remove-IfPointsHere([string]$key, [string]$folder) {
    # Default-browser registration (safari_browser.py default_browser_registry), only when it's this copy's.
    try {
        $command = (Get-ItemProperty -LiteralPath "$key\shell\open\command" -ErrorAction Stop).'(default)'
        if ($command -and $command.IndexOf($folder, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Remove-Item -LiteralPath $key -Recurse -Force
            return $true
        }
    } catch { }
    return $false
}

function Remove-Registration([string]$folder) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($place in 'Desktop', 'Programs') {
        $link = Join-Path ([Environment]::GetFolderPath($place)) 'Huginn.lnk'
        if (Test-Path -LiteralPath $link) {
            $points = $shell.CreateShortcut($link).TargetPath
            if ($points -and (Test-Inside $points $folder)) { Remove-Item -LiteralPath $link -Force }
        }
    }
    $client = 'HKCU:\Software\Clients\StartMenuInternet\Huginn'
    if (Remove-IfPointsHere $client $folder) {
        Remove-IfPointsHere 'HKCU:\Software\Classes\HuginnURL' $folder | Out-Null
        Remove-IfPointsHere 'HKCU:\Software\Classes\HuginnHTML' $folder | Out-Null
        Remove-ItemProperty -Path 'HKCU:\Software\RegisteredApplications' -Name 'Huginn' -ErrorAction SilentlyContinue
    }
    try {
        $entry = Get-ItemProperty -LiteralPath $AppsKey -ErrorAction Stop
        if (Test-Same $entry.InstallLocation $folder) { Remove-Item -LiteralPath $AppsKey -Recurse -Force }
    } catch { }
}

function Get-BuildFolder([string]$folder) {
    # A build that was stopped part-way leaves its work folder (tens of GB) behind; it goes too.
    try {
        $state = Get-Content -LiteralPath (Join-Path $folder 'engine\state.json') -Raw | ConvertFrom-Json
        if ($state.work -and (Split-Path -Leaf $state.work) -ieq 'sqtb' -and (Test-Path -LiteralPath $state.work)) {
            return [string]$state.work
        }
    } catch { }
    return $null
}

function Start-Remove {
    $S.removing = $true
    $ui.Heading.Text = 'Removing Huginn'
    $ui.Lead.Text = 'This only takes a moment.'
    $ui.StepText1.Text = 'Closing Huginn'
    $ui.StepText2.Text = 'Removing shortcuts and registration'
    $ui.StepText3.Text = 'Removing files'
    $ui.StepText4.Text = 'Removing bookmarks, history and settings'
    foreach ($i in 1..5) { Set-Step $i 'Wait' '' }
    $ui.StepText5.Parent.Visibility = 'Collapsed'
    if (-not $ui.DataSwitch.IsChecked) { $ui.StepText4.Parent.Visibility = 'Collapsed' }
    $ui.StopButton.Visibility = 'Collapsed'
    Show-Page 'PageProgress'
    Set-Location -LiteralPath $env:TEMP
    Set-Step 1 'Run'
    $S.closing = Get-HuginnProcesses $S.target
    foreach ($p in $S.closing) {
        try { [void](Get-Process -Id $p.ProcessId -ErrorAction Stop).CloseMainWindow() } catch { }
    }
    $S.closeSince = Get-Date
    $S.phase = 'closing'
    Set-Detail $(if ($S.closing.Count) { 'Asking Huginn to close (your tabs are saved)' } else { 'Huginn isn''t open' })
    $timer.Start()
}

function Tick-Remove {
    if ($S.phase -eq 'closing') {
        $left = @(Get-HuginnProcesses $S.target)
        if ($left.Count -and ((Get-Date) - $S.closeSince).TotalSeconds -lt 10) { return }
        foreach ($p in $left) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
        Set-Step 1 'Done' ''
        Set-Progress 0.2
        Set-Step 2 'Run'
        try { Remove-Registration $S.target } catch { }
        Set-Step 2 'Done' ''
        Set-Progress 0.35
        Set-Step 3 'Run'
        Set-Detail $S.target
        $folders = @($S.target)
        $build = Get-BuildFolder $S.target
        if ($build) { $folders += $build }
        $quoted = ($folders | ForEach-Object { 'rmdir /s /q "' + $_ + '"' }) -join ' & '
        $S.proc = Start-Hidden 'cmd.exe' ('/d /c ' + $quoted) $env:TEMP
        $S.phase = 'removing'
    } elseif ($S.phase -eq 'removing') {
        Set-Progress ([Math]::Min(0.85, $S.fraction + 0.01))
        if (-not $S.proc.HasExited) { return }
        $left = Test-Path -LiteralPath $S.target
        Set-Step 3 $(if ($left) { 'Fail' } else { 'Done' }) ''
        if ($ui.DataSwitch.IsChecked) {
            Set-Step 4 'Run'
            try {
                if (Test-Path -LiteralPath $DataDir) {
                    Get-ChildItem -LiteralPath $DataDir -Force | Where-Object { $KeepInData -notcontains $_.Name } |
                        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
                    if (-not (Get-ChildItem -LiteralPath $DataDir -Force)) { Remove-Item -LiteralPath $DataDir -Force }
                }
                Remove-Item -LiteralPath $SettingsKey -Recurse -Force -ErrorAction SilentlyContinue
                Set-Step 4 'Done' ''
            } catch { Set-Step 4 'Fail' '' }
        }
        $timer.Stop()
        $S.phase = ''
        Set-Progress 1.0
        $ui.Heading.Text = 'Huginn has been removed'
        $ui.Lead.Text = 'Thanks for flying with the ravens.'
        $ui.DoneList.Children.Clear()
        if ($left) { Add-DoneLine ('A few files were in use. Delete ' + $S.target + ' after restarting your PC.') }
        else { Add-DoneLine 'Huginn, its engine and its shortcuts are gone.' }
        if ($ui.DataSwitch.IsChecked) { Add-DoneLine 'Your bookmarks, history, passwords and settings were removed too.' }
        else { Add-DoneLine 'Your bookmarks, history, passwords and settings were kept, ready if you install Huginn again.' }
        $ui.OpenButton.Visibility = 'Collapsed'
        $ui.CloseButton.IsDefault = $true
        Show-Page 'PageDone'
    }
}

# ------------------------------------------------------------------------------------------ wiring
$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(150)
$timer.Add_Tick({
    try { if ($S.removing) { Tick-Remove } else { Tick-Install } }
    catch {
        if ($S.removing) { $timer.Stop(); $ui.DetailText.Text = $_.Exception.Message }
        else { Fail-Install 3 $_.Exception.Message }
    }
})

$logo = Get-Logo (Join-Path $Source 'Huginn.ico')
if ($null -ne $logo) { $ui.Logo.Source = $logo; $window.Icon = $logo }

$window.Add_MouseLeftButtonDown({ try { $window.DragMove() } catch { } })
$ui.CloseDot.Add_Click({ $window.Close() })
$ui.MinDot.Add_Click({ $window.WindowState = 'Minimized' })
$window.Add_Closing({
    param($sender, $e)
    if ($S.phase -eq 'removing' -or $S.phase -eq 'closing') { $e.Cancel = $true; return }   # let removal finish
    $timer.Stop()
    Stop-Tree $S.proc
})

$ui.ChangeButton.Add_Click({
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose where to put Huginn (a "Huginn" folder is made inside).'
    $dialog.ShowNewFolderButton = $true
    $dialog.SelectedPath = Split-Path -Parent $S.target
    if ($dialog.ShowDialog() -eq 'OK') {
        $picked = $dialog.SelectedPath
        if ((Split-Path -Leaf $picked) -ine 'Huginn') { $picked = Join-Path $picked 'Huginn' }
        Set-Target $picked
    }
})
$ui.CancelButton.Add_Click({ $window.Close() })
$ui.InstallButton.Add_Click({ try { Start-Install } catch { Fail-Install 1 $_.Exception.Message } })
$ui.StopButton.Add_Click({
    if ($S.stopped) { $window.Close(); return }
    $timer.Stop()
    Stop-Tree $S.proc
    $S.phase = ''
    $S.stopped = $true
    Set-Detail 'Stopped. Run the installer again any time; it carries on where it left off.'
    foreach ($i in 1..5) { if ($ui["Run$i"].Visibility -eq 'Visible') { Set-Step $i 'Fail' 'stopped' } }
    $ui.StopButton.Content = 'Close'
})
$ui.CloseButton.Add_Click({ $window.Close() })
$ui.FailCloseButton.Add_Click({ $window.Close() })
$ui.OpenButton.Add_Click({
    $pythonw = Join-Path $S.target 'python\pythonw.exe'
    Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $S.target 'safari_browser.py') + '"') -WorkingDirectory $S.target
    $window.Close()
})
$ui.LogButton.Add_Click({
    $log = Join-Path $S.target 'setup.log'
    if (Test-Path -LiteralPath $log) { Start-Process notepad.exe -ArgumentList ('"' + $log + '"') }
})
$ui.RetryButton.Add_Click({ $S.failed = $false; try { Start-Install } catch { Fail-Install 1 $_.Exception.Message } })
$ui.KeepButton.Add_Click({ $window.Close() })
$ui.RemoveButton.Add_Click({ try { Start-Remove } catch { $ui.DetailText.Text = $_.Exception.Message } })

# ------------------------------------------------------------------------------------------ start
if ($Uninstall) {
    $S.target = $Source
    $window.Title = 'Remove Huginn'
    $ui.Heading.Text = 'Remove Huginn'
    $ui.Lead.Text = 'Huginn, its engine and its shortcuts will be removed from this PC.'
    $ui.RemovePath.Text = $Source
    $ui.RemovePath.ToolTip = $Source
    Show-Page 'PageRemove'
} else {
    if (-not [Environment]::Is64BitOperatingSystem) {
        [Windows.MessageBox]::Show('Huginn needs 64-bit Windows 10 or 11.', 'Huginn') | Out-Null
        exit 1
    }
    $ui.Lead.Text = 'A quiet, private browser, named for Odin''s raven of thought. Setup takes a few minutes.'
    $existing = $null
    try { $existing = (Get-ItemProperty -LiteralPath $AppsKey -ErrorAction Stop).InstallLocation } catch { }
    if ($Target) { Set-Target $Target }
    elseif ($existing -and (Test-Path -LiteralPath (Join-Path $existing 'safari_browser.py'))) {
        Set-Target $existing                                    # updating / repairing an existing install
        $S.update = $true
        $ui.Heading.Text = 'Update Huginn'
        $ui.InstallButton.Content = 'Update'
    }
    else { Set-Target $DefaultTarget }
    $hours = Get-BuildHours
    $drive = Get-BuildDrive
    $ui.VideoText.Text = ('So Twitch, Reddit, X and news-site videos play. Huginn compiles it in the background ' +
                          'after install, about {0}–{1} hours on this PC at low priority, with {2} GB free while ' +
                          'it works. Windows asks once to add Microsoft''s free C++ Build Tools.') -f $hours[0], $hours[1], $BuildGB
    if ($null -eq $drive -or $drive.gb -lt $BuildGB) {
        $ui.VideoSwitch.IsEnabled = $false
        $free = if ($drive) { '{0} has {1:0} GB' -f $drive.name, $drive.gb } else { 'no drive was found' }
        $ui.VideoText.Text = ('So Twitch, Reddit, X and news-site videos play. It needs about {0} GB free while it ' +
                              'builds ({1}); you can start it later from Privacy & Security › Video.') -f $BuildGB, $free
    }
    Show-Page 'PageOptions'
}
[void]$window.ShowDialog()
