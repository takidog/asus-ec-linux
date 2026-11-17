/* Local hwmon integration, tested against Proxmox VE 8.4. */
(function () {
    // Ext JS 7 callParent inspects Function.caller; its override methods must
    // remain non-strict. Strict mode breaks node summary construction.
    function format(data, group, empty) {
        const readings = data && data[group];
        if (!Array.isArray(readings) || !readings.length) {
            return empty || 'Unavailable';
        }
        return readings.map(function (reading) {
            if (!Number.isFinite(reading.value)) {
                return 'Unavailable';
            }
            const label = Ext.String.htmlEncode(reading.label || '');
            const unit = group === 'fans' ? ' RPM' : '\u00b0C';
            const value = Number(reading.value.toFixed(1));
            const high = Number.isFinite(reading.max) && value >= reading.max;
            const critical = Number.isFinite(reading.crit) && value >= reading.crit;
            const color = critical ? 'var(--pwt-text-color-critical, #d22)' :
                high ? 'var(--pwt-text-color-warning, #b86b00)' : 'inherit';
            return '<span style="display:inline-block;margin-right:10px;color:' + color + '">' +
                label + ': ' + value + unit + '</span>';
        }).join(' ');
    }
    function row(title, group, extra) {
        return Object.assign({
            itemId: 'local-thermal-' + group,
            title: title,
            iconCls: 'fa fa-fw fa-thermometer-half',
            printBar: false,
            textField: 'localthermal',
            value: 'Loading...',
            renderer: function (data) {
                return format(data, group, group === 'fans' ? 'No RPM sensor exposed' : null);
            },
        }, extra || {});
    }
    const modes = { normal: 'Normal', 'full-speed': 'Full speed', quiet: 'Quiet' };
    function fanReading(data) {
        const fan = data && data.ecfan;
        if (fan && fan.available && Number.isFinite(fan.fan_rpm)) {
            return 'CPU: ' + fan.fan_rpm + ' RPM';
        }
        return format(data, 'fans', fan && fan.reason === 'stale' ? 'Reading expired' : 'Unavailable');
    }
    Ext.define('PVE.localthermal.StatusView', {
        override: 'PVE.node.StatusView',
        localFanMessage: function (text) {
            const box = this.down('#local-fan-message');
            if (box) box.update(Ext.String.htmlEncode(text));
        },
        localFanRefresh: function () {
            if (this.destroyed || this.destroying) return;
            const fan = this.localFanData || {};
            const elapsed = (Date.now() - (this.localFanReceived || 0)) / 1000;
            const fresh = fan.available && Number.isFinite(fan.age_seconds) && fan.age_seconds + elapsed < 15;
            const caps = Ext.state.Manager.get('GuiCap') || {};
            const allowed = !!(caps.nodes && caps.nodes['Sys.Modify']);
            const disabled = !fresh || !fan.control_supported || !allowed || this.localFanBusy;
            this.down('#local-fan-normal').setDisabled(disabled || fan.mode === 'normal');
            this.down('#local-fan-full-speed').setDisabled(disabled || fan.mode === 'full-speed');
            this.down('#local-fan-current').setValue('Fan mode: ' + (fresh ? (modes[fan.mode] || 'Unknown') : 'Unavailable'));
            if (!fresh && !this.localFanBusy) {
                this.localFanMessage('Fan readings unavailable. Waiting for the monitor.');
                const widget = this.down('#local-thermal-fans');
                if (fan.available && widget) widget.updateValue('Reading expired');
            } else if (!allowed && !this.localFanBusy) {
                this.localFanMessage('Viewing only. Changing fan mode requires Sys.Modify.');
            } else if (!fan.control_supported && !this.localFanBusy) {
                this.localFanMessage('This fan mode has not been verified for switching.');
            } else if (!this.localFanBusy && !this.localFanResult) {
                this.localFanMessage('Mode applies until firmware changes it or the host restarts.');
            }
        },
        localFanFinish: function (message) {
            if (this.destroyed || this.destroying) return;
            this.localFanBusy = false;
            this.localFanResult = message;
            this.localFanMessage(message);
            this.localFanRefresh();
            this.getStore().load();
        },
        localFanPoll: function (upid, deadline) {
            const me = this;
            if (me.destroyed || me.destroying) return;
            if (Date.now() >= deadline) {
                me.localFanFinish('Update not confirmed. Check the task log and current mode before retrying.');
                return;
            }
            const node = me.pveSelNode.data.node;
            Proxmox.Utils.API2Request({
                url: '/nodes/' + encodeURIComponent(node) + '/tasks/' + encodeURIComponent(upid) + '/status',
                method: 'GET', timeout: 4000,
                success: function (response) {
                    if (me.destroyed || me.destroying) return;
                    const task = response.result.data;
                    if (task.status === 'stopped') {
                        me.localFanFinish(task.exitstatus === 'OK' ? 'Fan mode updated.' : 'Update failed: ' + task.exitstatus);
                    } else {
                        me.localFanTaskTimer = Ext.defer(function () { me.localFanPoll(upid, deadline); }, 1000);
                    }
                },
                failure: function () {
                    me.localFanFinish('Task status unavailable. Check the task log and current mode before retrying.');
                },
            });
        },
        localFanSetMode: function (mode) {
            const me = this;
            const button = me.down('#local-fan-' + mode);
            if (!button || button.disabled || me.localFanBusy) return;
            me.localFanBusy = true;
            me.localFanResult = null;
            me.localFanMessage('Applying ' + modes[mode] + '...');
            me.localFanRefresh();
            Proxmox.Utils.API2Request({
                url: '/nodes/' + encodeURIComponent(me.pveSelNode.data.node) + '/localfan',
                method: 'PUT', params: { mode: mode }, timeout: 5000,
                success: function (response) {
                    if (!me.destroyed && !me.destroying) me.localFanPoll(response.result.data, Date.now() + 30000);
                },
                failure: function (response) {
                    me.localFanFinish('Update not confirmed: ' + (response.htmlStatus || 'request failed') +
                        '. Check the current mode before retrying.');
                },
            });
        },
        updateValues: function (store, records, success) {
            this.callParent(arguments);
            if (success) {
                const data = this.getRecordValue('localthermal') || {};
                this.localFanData = data.ecfan || {};
                this.localFanReceived = Date.now();
            }
            this.localFanRefresh();
        },
        initComponent: function () {
            const me = this;
            this.items = Ext.clone(this.items);
            const position = this.items.findIndex(function (item) { return item.itemId === 'cpus'; });
            this.items.splice(position < 0 ? this.items.length : position, 0,
                row('CPU temperature', 'cpu'),
                row('NVMe temperature', 'nvme'),
                row('CPU cores', 'cores', { colspan: 2 }),
                row('SATA temperatures', 'sata', { colspan: 2 }),
                row('ACPI temperature', 'acpi'),
                row('Fan speed', 'fans', { iconCls: 'fa fa-fw fa-tachometer', renderer: fanReading }),
                {
                    xtype: 'container', colspan: 2, layout: { type: 'vbox', align: 'stretch' },
                    padding: '0 10 10 10',
                    items: [
                        { xtype: 'container', layout: 'hbox', items: [
                            { xtype: 'displayfield', itemId: 'local-fan-current', value: 'Fan mode: Loading...', flex: 1 },
                            { xtype: 'button', itemId: 'local-fan-normal', text: 'Normal', width: 90,
                              disabled: true, margin: '0 6 0 0', tooltip: 'Use the firmware automatic fan policy',
                              handler: function () { me.localFanSetMode('normal'); } },
                            { xtype: 'button', itemId: 'local-fan-full-speed', text: 'Full speed', width: 110,
                              disabled: true, tooltip: 'Disable QFan and run the CPU fan at full speed',
                              handler: function () { me.localFanSetMode('full-speed'); } },
                        ] },
                        { xtype: 'box', itemId: 'local-fan-message', ariaRole: 'status',
                          style: 'white-space:normal;overflow-wrap:anywhere', html: 'Waiting for fan readings...' },
                    ],
                },
                { xtype: 'box', colspan: 2, padding: '0 0 15 0' });
            this.height = Math.max(this.height || 350, 565);
            this.callParent(arguments);
            function tick() {
                if (me.destroyed || me.destroying) return;
                me.localFanRefresh();
                me.localFanAgeTimer = Ext.defer(tick, 1000);
            }
            me.localFanAgeTimer = Ext.defer(tick, 1000);
            me.on('destroy', function () {
                clearTimeout(me.localFanAgeTimer);
                clearTimeout(me.localFanTaskTimer);
            });
        },
    });
})();
