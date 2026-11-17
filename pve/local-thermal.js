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
    Ext.define('PVE.localthermal.StatusView', {
        override: 'PVE.node.StatusView',
        initComponent: function () {
            this.items = Ext.clone(this.items);
            const position = this.items.findIndex(function (item) { return item.itemId === 'cpus'; });
            this.items.splice(position < 0 ? this.items.length : position, 0,
                row('CPU temperature', 'cpu'),
                row('NVMe temperature', 'nvme'),
                row('CPU cores', 'cores', { colspan: 2 }),
                row('SATA temperatures', 'sata', { colspan: 2 }),
                row('ACPI temperature', 'acpi'),
                row('Fan speed', 'fans', { iconCls: 'fa fa-fw fa-tachometer' }),
                { xtype: 'box', colspan: 2, padding: '0 0 15 0' });
            this.height = Math.max(this.height || 350, 490);
            this.callParent(arguments);
        },
    });
})();
